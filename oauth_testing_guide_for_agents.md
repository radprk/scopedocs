# Comprehensive OAuth 2.0 Testing Guide for Coding Agents

## Table of Contents
1. [Introduction](#introduction)
2. [Understanding OAuth 2.0 Flows](#understanding-oauth-20-flows)
3. [Testing Philosophy](#testing-philosophy)
4. [Unit Testing Strategy](#unit-testing-strategy)
5. [Integration Testing Strategy](#integration-testing-strategy)
6. [Security Testing Checklist](#security-testing-checklist)
7. [Implementation Guidelines](#implementation-guidelines)
8. [Common Pitfalls to Avoid](#common-pitfalls-to-avoid)
9. [Testing Tools and Frameworks](#testing-tools-and-frameworks)

---

## Introduction

### Purpose
This guide provides coding agents with a systematic approach to testing OAuth 2.0 implementations. It combines security best practices from RFC 9700 (OAuth 2.0 Security Best Current Practice, January 2025) with practical testing methodologies.

### Key Concepts
- **Authentication vs Authorization**: This guide focuses on OAuth **authorization** (granting permissions), though the term "authentication" is commonly used in practice
- **Security-First Mindset**: OAuth client vulnerabilities can be exploited to access connected services, making security testing critical
- **Test Coverage**: Testing goes beyond "happy path" to include error handling, security threats, and edge cases

---

## Understanding OAuth 2.0 Flows

### Recommended Flows (2025 Standards)

#### 1. Authorization Code Flow with PKCE
**Primary use case**: All client types (web apps, SPAs, native apps, mobile apps)
**Status**: REQUIRED for public clients, RECOMMENDED for confidential clients

**Why PKCE is essential**:
- Prevents authorization code interception attacks
- Protects against CSRF (Cross-Site Request Forgery)
- Works even if client secret is compromised
- Required by RFC 9700 for public clients

**Flow Overview**:
```
User → Client generates code_verifier & code_challenge
     → Client redirects to /authorize with code_challenge
     → User authenticates & authorizes
     → Authorization Server redirects with authorization code
     → Client exchanges code + code_verifier for tokens at /token
     → Authorization Server verifies code_challenge matches code_verifier
     → Tokens issued
```

#### 2. Client Credentials Flow
**Primary use case**: Machine-to-machine communication (no user involved)
**Status**: Acceptable for server-to-server authentication

#### 3. Refresh Token Flow
**Primary use case**: Getting new access tokens without re-authentication
**Status**: Required for long-lived sessions

### Deprecated Flows (DO NOT USE)

#### ❌ Implicit Flow
**Status**: DEPRECATED in OAuth 2.1
**Why**: Exposes tokens in browser history, vulnerable to XSS attacks, less secure than PKCE
**Exception**: Still valid for retrieving ID tokens in OpenID Connect

#### ❌ Resource Owner Password Credentials (ROPC)
**Status**: DEPRECATED in OAuth 2.1
**Why**: Requires sharing user credentials directly with client, defeats OAuth's purpose
**Exception**: Only for legacy migrations

---

## Testing Philosophy

### The Testing Pyramid for OAuth

```
           /\
          /  \         E2E/Integration Tests
         /    \        - Full OAuth flow
        /      \       - User interaction simulation
       /--------\      - External service integration
      /          \
     /            \    Unit Tests
    /              \   - Token validation
   /                \  - State management
  /                  \ - Error handling
 /____________________\
```

### Test Categories

1. **Unit Tests**: Test individual components in isolation
2. **Integration Tests**: Test OAuth flow end-to-end with real or mock services
3. **Security Tests**: Verify protection against known attack vectors
4. **Error Handling Tests**: Verify graceful degradation and error states

---

## Unit Testing Strategy

### Principle: Mock the OAuth Provider

In unit tests, you should **NEVER** make actual requests to OAuth providers. Instead, mock the responses you'd receive from the authorization server.

### What to Unit Test

#### Step 1: Authorization Code Request (GET /authorize)

**Route Responsibility**: Redirect user to authorization server

**Tests to Implement**:

```python
# Test: Verify 3xx redirect response
def test_authorization_redirect_returns_3xx():
    response = client.get('/auth/login')
    assert response.status_code in [301, 302, 303, 307, 308]

# Test: Verify client_id is read from secure storage
def test_client_id_loaded_from_secure_config():
    with patch('config.get_secret') as mock_get:
        mock_get.return_value = 'test_client_id'
        response = client.get('/auth/login')
        mock_get.assert_called_with('oauth_client_id')

# Test: Verify redirect_uri matches registered URI
def test_redirect_uri_matches_registered():
    response = client.get('/auth/login')
    location = response.headers.get('Location')
    assert 'redirect_uri=https://myapp.com/auth/callback' in location

# Test: Verify state parameter is unique and non-guessable
def test_state_parameter_is_unique():
    response1 = client.get('/auth/login')
    response2 = client.get('/auth/login')
    state1 = extract_state_from_location(response1.headers['Location'])
    state2 = extract_state_from_location(response2.headers['Location'])
    
    assert state1 != state2
    assert len(state1) >= 32  # Sufficient entropy
    assert state1.isalnum()   # No predictable patterns

# Test: Verify state is stored securely (session/database)
def test_state_stored_in_session():
    with client.session_transaction() as session:
        client.get('/auth/login')
        assert 'oauth_state' in session
        assert len(session['oauth_state']) >= 32

# Test: PKCE - code_verifier generated
def test_pkce_code_verifier_generated():
    with client.session_transaction() as session:
        client.get('/auth/login')
        assert 'pkce_code_verifier' in session
        # Verifier should be 43-128 characters (base64url encoded)
        assert 43 <= len(session['pkce_code_verifier']) <= 128

# Test: PKCE - code_challenge derived correctly
def test_pkce_code_challenge_is_sha256_of_verifier():
    import hashlib
    import base64
    
    response = client.get('/auth/login')
    location = response.headers['Location']
    
    with client.session_transaction() as session:
        verifier = session['pkce_code_verifier']
    
    # Calculate expected challenge
    digest = hashlib.sha256(verifier.encode()).digest()
    expected_challenge = base64.urlsafe_b64encode(digest).decode().rstrip('=')
    
    assert f'code_challenge={expected_challenge}' in location
    assert 'code_challenge_method=S256' in location

# Test: Verify scopes are included if required
def test_required_scopes_included():
    response = client.get('/auth/login')
    location = response.headers.get('Location')
    assert 'scope=read_user+read_calendar' in location
```

#### Step 2: Authorization Callback (GET /callback)

**Route Responsibility**: Receive authorization code, exchange for token

**Tests to Implement**:

```python
# Test: Reject request if state doesn't match
def test_callback_rejects_mismatched_state():
    with client.session_transaction() as session:
        session['oauth_state'] = 'valid_state_123'
    
    response = client.get('/auth/callback?code=auth_code&state=wrong_state')
    assert response.status_code in [400, 403]  # Reject the request

# Test: Accept request when state matches
def test_callback_accepts_matching_state():
    with client.session_transaction() as session:
        session['oauth_state'] = 'valid_state_123'
        session['pkce_code_verifier'] = 'test_verifier'
    
    with patch('oauth_client.exchange_code') as mock_exchange:
        mock_exchange.return_value = {'access_token': 'token123'}
        response = client.get('/auth/callback?code=auth_code&state=valid_state_123')
        assert response.status_code == 302  # Successful redirect

# Test: Handle missing state parameter
def test_callback_handles_missing_state():
    response = client.get('/auth/callback?code=auth_code')
    assert response.status_code in [400, 403]

# Test: Handle missing code parameter
def test_callback_handles_missing_code():
    with client.session_transaction() as session:
        session['oauth_state'] = 'valid_state_123'
    
    response = client.get('/auth/callback?state=valid_state_123')
    assert response.status_code in [400, 403]

# Test: Handle authorization denial (error parameter)
def test_callback_handles_user_denial():
    with client.session_transaction() as session:
        session['oauth_state'] = 'valid_state_123'
    
    response = client.get('/auth/callback?error=access_denied&state=valid_state_123')
    assert response.status_code in [302, 400]  # Redirect or error page
```

#### Step 3: Token Exchange (POST /token)

**Component Responsibility**: Exchange authorization code for access token

**Tests to Implement**:

```python
# Test: Mock successful token exchange
def test_exchange_code_for_token_success():
    mock_response = {
        'access_token': 'access_token_123',
        'token_type': 'Bearer',
        'expires_in': 3600,
        'refresh_token': 'refresh_token_456'
    }
    
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.status_code = 200
        
        token = oauth_client.exchange_code('auth_code_123', 'verifier_abc')
        
        assert token['access_token'] == 'access_token_123'
        assert 'refresh_token' in token

# Test: Verify client_id and client_secret in request
def test_token_exchange_uses_client_credentials():
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = {'access_token': 'token'}
        mock_post.return_value.status_code = 200
        
        oauth_client.exchange_code('auth_code', 'verifier')
        
        # Verify credentials sent in request body (not headers)
        call_data = mock_post.call_args[1]['data']
        assert 'client_id' in call_data
        assert 'client_secret' in call_data

# Test: PKCE - code_verifier included in token request
def test_token_exchange_includes_code_verifier():
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = {'access_token': 'token'}
        mock_post.return_value.status_code = 200
        
        oauth_client.exchange_code('auth_code', 'verifier_xyz')
        
        call_data = mock_post.call_args[1]['data']
        assert call_data['code_verifier'] == 'verifier_xyz'

# Test: Handle token exchange failure
def test_token_exchange_handles_error():
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = {
            'error': 'invalid_grant',
            'error_description': 'Code expired'
        }
        mock_post.return_value.status_code = 400
        
        with pytest.raises(OAuthException):
            oauth_client.exchange_code('invalid_code', 'verifier')

# Test: Tokens stored securely
def test_tokens_stored_in_secure_storage():
    with patch('secure_storage.save') as mock_save:
        mock_token = {'access_token': 'token123', 'refresh_token': 'refresh456'}
        oauth_client.save_tokens(user_id='user_1', tokens=mock_token)
        
        mock_save.assert_called_once()
        # Verify encryption or secure storage mechanism
        saved_data = mock_save.call_args[0][0]
        assert 'access_token' in saved_data
```

#### Step 4: Using Access Tokens

**Component Responsibility**: Make authenticated API requests

**Tests to Implement**:

```python
# Test: Access token included in Authorization header
def test_api_request_includes_bearer_token():
    with patch('requests.get') as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'data': 'success'}
        
        api_client.get_user_profile('access_token_123')
        
        headers = mock_get.call_args[1]['headers']
        assert headers['Authorization'] == 'Bearer access_token_123'

# Test: Handle token expiration (401 response)
def test_handle_token_expiration():
    with patch('requests.get') as mock_get:
        mock_get.return_value.status_code = 401
        mock_get.return_value.json.return_value = {
            'error': 'invalid_token',
            'error_description': 'Token expired'
        }
        
        with pytest.raises(TokenExpiredException):
            api_client.get_user_profile('expired_token')

# Test: Automatic token refresh on 401
def test_automatic_token_refresh_on_401():
    with patch('requests.get') as mock_get, \
         patch('oauth_client.refresh_token') as mock_refresh:
        
        # First call returns 401, second succeeds
        mock_get.side_effect = [
            Mock(status_code=401, json=lambda: {'error': 'invalid_token'}),
            Mock(status_code=200, json=lambda: {'data': 'success'})
        ]
        mock_refresh.return_value = 'new_access_token'
        
        result = api_client.get_user_profile_with_retry('old_token', 'refresh_token')
        
        # Verify refresh was called
        mock_refresh.assert_called_once_with('refresh_token')
        # Verify second request used new token
        assert result['data'] == 'success'

# Test: Don't retry if no refresh token available
def test_no_retry_without_refresh_token():
    with patch('requests.get') as mock_get:
        mock_get.return_value.status_code = 401
        
        # Should not attempt refresh without refresh_token
        with pytest.raises(TokenExpiredException):
            api_client.get_user_profile_with_retry('expired_token', refresh_token=None)
```

#### Step 5: Token Refresh

**Component Responsibility**: Obtain new access token using refresh token

**Tests to Implement**:

```python
# Test: Successful token refresh
def test_refresh_token_success():
    mock_response = {
        'access_token': 'new_access_token',
        'token_type': 'Bearer',
        'expires_in': 3600,
        'refresh_token': 'new_refresh_token'  # May or may not be present
    }
    
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.status_code = 200
        
        new_tokens = oauth_client.refresh_access_token('old_refresh_token')
        
        assert new_tokens['access_token'] == 'new_access_token'

# Test: Replace both tokens if new refresh_token provided
def test_replace_both_tokens_on_refresh():
    mock_response = {
        'access_token': 'new_access',
        'refresh_token': 'new_refresh'
    }
    
    with patch('requests.post') as mock_post, \
         patch('secure_storage.update') as mock_update:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.status_code = 200
        
        oauth_client.refresh_access_token('old_refresh')
        
        # Verify both tokens updated
        updated_tokens = mock_update.call_args[0][0]
        assert updated_tokens['access_token'] == 'new_access'
        assert updated_tokens['refresh_token'] == 'new_refresh'

# Test: Keep old refresh_token if not provided in response
def test_keep_old_refresh_token_if_not_returned():
    mock_response = {
        'access_token': 'new_access'
        # No refresh_token in response
    }
    
    with patch('requests.post') as mock_post, \
         patch('secure_storage.get') as mock_get, \
         patch('secure_storage.update') as mock_update:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.status_code = 200
        mock_get.return_value = {'refresh_token': 'old_refresh'}
        
        oauth_client.refresh_access_token('old_refresh')
        
        updated_tokens = mock_update.call_args[0][0]
        assert updated_tokens['access_token'] == 'new_access'
        assert updated_tokens['refresh_token'] == 'old_refresh'  # Unchanged

# Test: Handle refresh token expiration
def test_handle_refresh_token_expiration():
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            'error': 'invalid_grant',
            'error_description': 'Refresh token expired'
        }
        
        # Should trigger re-authentication flow
        with pytest.raises(RefreshTokenExpiredException):
            oauth_client.refresh_access_token('expired_refresh')
```

---

## Integration Testing Strategy

### Principle: Test the Full Flow

Integration tests verify that all components work together correctly, simulating real user interactions with the OAuth provider.

### Test Environment Setup

#### Option 1: Use OAuth Provider's Test Environment
```python
# Example: Use Google's OAuth Playground or test credentials
TEST_OAUTH_CONFIG = {
    'client_id': 'test_client_id_from_provider',
    'client_secret': 'test_client_secret',
    'authorization_url': 'https://accounts.google.com/o/oauth2/v2/auth',
    'token_url': 'https://oauth2.googleapis.com/token',
    'redirect_uri': 'http://localhost:5000/auth/callback'
}
```

#### Option 2: Mock OAuth Server
```python
# Use libraries like responses, HTTPretty, or mock-oauth2-server
# Example with responses library:

import responses

@responses.activate
def test_full_oauth_flow():
    # Mock authorization endpoint
    responses.add(
        responses.GET,
        'https://oauth.example.com/authorize',
        status=302,
        headers={'Location': 'http://localhost:5000/callback?code=test_code&state=test_state'}
    )
    
    # Mock token endpoint
    responses.add(
        responses.POST,
        'https://oauth.example.com/token',
        json={'access_token': 'test_access_token', 'token_type': 'Bearer'},
        status=200
    )
    
    # Run your OAuth flow
    result = perform_oauth_flow()
    assert result['access_token'] == 'test_access_token'
```

### Integration Test Cases

#### Test 1: Complete Authorization Code Flow

```python
def test_complete_authorization_code_flow():
    """
    Simulates full user journey:
    1. User clicks "Login with Provider"
    2. Redirected to provider
    3. User authenticates
    4. Redirected back with code
    5. Code exchanged for token
    6. Token used to access resource
    """
    
    # Step 1: Initiate OAuth flow
    response = client.get('/auth/login')
    assert response.status_code == 302
    
    # Extract state and redirect URL
    location = response.headers['Location']
    state = extract_param(location, 'state')
    
    # Step 2: Simulate OAuth provider callback
    # (In real test, you might use Selenium/Playwright to actually interact)
    callback_response = client.get(
        f'/auth/callback?code=test_auth_code&state={state}'
    )
    
    # Step 3: Verify tokens stored and user redirected
    assert callback_response.status_code == 302
    assert '/dashboard' in callback_response.headers['Location']
    
    # Step 4: Verify can make authenticated requests
    with client.session_transaction() as session:
        access_token = session.get('access_token')
        assert access_token is not None
```

#### Test 2: PKCE Flow Verification

```python
def test_pkce_flow_integrity():
    """
    Verify PKCE parameters work correctly:
    - code_verifier generated
    - code_challenge derived correctly
    - code_verifier sent during token exchange
    - Authorization server validates matching challenge
    """
    
    # Initiate flow
    with client.session_transaction() as session:
        client.get('/auth/login')
        code_verifier = session['pkce_code_verifier']
    
    # Simulate callback with authorization code
    with patch('requests.post') as mock_post:
        def validate_pkce(url, data=None, **kwargs):
            # Verify code_verifier sent in token request
            assert data.get('code_verifier') == code_verifier
            
            # Simulate authorization server validation
            # (In reality, server checks: SHA256(code_verifier) == code_challenge)
            return Mock(
                status_code=200,
                json=lambda: {'access_token': 'token_xyz'}
            )
        
        mock_post.side_effect = validate_pkce
        
        response = client.get('/auth/callback?code=test_code&state=test_state')
        
        # Verify successful token exchange
        assert mock_post.called
```

#### Test 3: Error Handling in Full Flow

```python
def test_oauth_flow_handles_user_denial():
    """
    Test when user denies authorization
    """
    response = client.get('/auth/callback?error=access_denied&state=valid_state')
    
    assert response.status_code in [302, 400]
    # Should redirect to error page or show error message
    assert 'Authorization was denied' in response.data.decode()

def test_oauth_flow_handles_expired_code():
    """
    Test when authorization code has expired
    """
    with client.session_transaction() as session:
        session['oauth_state'] = 'valid_state'
    
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            'error': 'invalid_grant',
            'error_description': 'Code expired'
        }
        
        response = client.get('/auth/callback?code=expired_code&state=valid_state')
        
        # Should handle gracefully
        assert response.status_code in [302, 400]
```

#### Test 4: Token Refresh Integration

```python
def test_automatic_token_refresh_integration():
    """
    Test that expired tokens are automatically refreshed
    """
    # Set up: User has expired access token but valid refresh token
    with client.session_transaction() as session:
        session['access_token'] = 'expired_token'
        session['refresh_token'] = 'valid_refresh_token'
    
    with patch('requests.get') as mock_api_get, \
         patch('requests.post') as mock_refresh_post:
        
        # First API call fails with 401
        mock_api_get.side_effect = [
            Mock(status_code=401, json=lambda: {'error': 'invalid_token'}),
            Mock(status_code=200, json=lambda: {'data': 'success'})
        ]
        
        # Refresh endpoint returns new token
        mock_refresh_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                'access_token': 'new_access_token',
                'refresh_token': 'new_refresh_token'
            }
        )
        
        # Make request that should trigger refresh
        response = client.get('/api/protected-resource')
        
        # Verify refresh was called
        assert mock_refresh_post.called
        assert mock_api_get.call_count == 2  # Original + retry
        
        # Verify new token stored
        with client.session_transaction() as session:
            assert session['access_token'] == 'new_access_token'
```

---

## Security Testing Checklist

### CRITICAL: State Parameter Protection (CSRF)

**Attack**: Cross-Site Request Forgery
**Impact**: Attacker can authenticate victim using attacker's account

```python
# ✅ SECURE: Unique, non-guessable state for each request
def test_state_prevents_csrf():
    # Attacker cannot predict state values
    states = [generate_state() for _ in range(100)]
    assert len(set(states)) == 100  # All unique
    
    # State has sufficient entropy (at least 32 chars)
    for state in states:
        assert len(state) >= 32
        # Should be cryptographically random
        assert not state.startswith('user_') # No predictable patterns

# ❌ INSECURE: Using same state or predictable values
def test_detect_insecure_state():
    # This would be INSECURE:
    # state = f"user_{user_id}_{timestamp}"  # Predictable!
    # state = "static_value"  # Never changes!
    pass
```

**Test Implementation**:

```python
def test_state_parameter_security():
    """Comprehensive state parameter security test"""
    
    # Test 1: State is unique per request
    response1 = client.get('/auth/login')
    response2 = client.get('/auth/login')
    state1 = extract_state(response1.headers['Location'])
    state2 = extract_state(response2.headers['Location'])
    assert state1 != state2
    
    # Test 2: State is non-guessable (high entropy)
    import math
    entropy = calculate_entropy(state1)
    assert entropy >= 128  # bits of entropy
    
    # Test 3: State mismatch is rejected
    with client.session_transaction() as session:
        session['oauth_state'] = 'valid_state_abc'
    
    response = client.get('/auth/callback?code=test&state=wrong_state')
    assert response.status_code in [400, 403]
    
    # Test 4: Missing state is rejected
    response = client.get('/auth/callback?code=test')
    assert response.status_code in [400, 403]
    
    # Test 5: State is cleared after use (replay protection)
    with client.session_transaction() as session:
        session['oauth_state'] = 'one_time_state'
    
    client.get('/auth/callback?code=test&state=one_time_state')
    
    # Attempting to reuse should fail
    response = client.get('/auth/callback?code=test2&state=one_time_state')
    assert response.status_code in [400, 403]

def calculate_entropy(string):
    """Calculate Shannon entropy of a string"""
    import math
    from collections import Counter
    
    if not string:
        return 0
    
    counts = Counter(string)
    probabilities = [count / len(string) for count in counts.values()]
    entropy = -sum(p * math.log2(p) for p in probabilities)
    
    # Return in bits
    return entropy * len(string)
```

### CRITICAL: Redirect URI Validation

**Attack**: Open Redirect / Authorization Code Interception
**Impact**: Attacker intercepts authorization code and exchanges it for tokens

```python
def test_redirect_uri_validation():
    """
    Redirect URI MUST match exactly what's registered.
    Even subtle differences should be rejected.
    """
    
    # ✅ SECURE: Exact match required
    REGISTERED_URI = "https://myapp.com/auth/callback"
    
    # ❌ INSECURE: These should all be REJECTED
    malicious_attempts = [
        "https://myapp.com/auth/callback/extra",  # Path addition
        "https://myapp.com/auth/callback?evil=true",  # Query param
        "https://evil.com?redirect=https://myapp.com/auth/callback",  # Wrong domain
        "http://myapp.com/auth/callback",  # Protocol downgrade
        "https://myapp.com.evil.com/auth/callback",  # Subdomain addition
        "https://myapp.com:8080/auth/callback",  # Port change (unless registered)
    ]
    
    for malicious_uri in malicious_attempts:
        # Authorization server should reject these
        # Your client should only accept exact match
        assert not is_valid_redirect_uri(malicious_uri, REGISTERED_URI)
```

### CRITICAL: PKCE Implementation (Public Clients)

**Attack**: Authorization Code Interception
**Impact**: Stolen code cannot be exchanged without code_verifier

```python
def test_pkce_implementation():
    """
    PKCE is MANDATORY for public clients (SPAs, mobile, native apps)
    RECOMMENDED for confidential clients
    """
    
    # Test 1: code_verifier generation
    verifier = generate_code_verifier()
    
    # Must be 43-128 characters, base64url encoded
    assert 43 <= len(verifier) <= 128
    assert all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~' 
               for c in verifier)
    
    # Test 2: code_challenge derivation
    import hashlib
    import base64
    
    challenge = generate_code_challenge(verifier)
    
    # Should be SHA256 hash of verifier, base64url encoded
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip('=')
    
    assert challenge == expected
    
    # Test 3: code_challenge_method must be S256 (not 'plain')
    # 'plain' method is insecure and deprecated
    assert get_code_challenge_method() == 'S256'
```

### Client Credential Storage

**Attack**: Credential Exposure
**Impact**: Attacker can impersonate your application

```python
def test_credential_security():
    """
    Credentials MUST NEVER be in source code
    """
    
    # ✅ SECURE: Read from environment or secret manager
    client_id = os.environ.get('OAUTH_CLIENT_ID')
    client_secret = get_secret_from_vault('oauth_client_secret')
    
    # ❌ INSECURE: These patterns should NEVER appear
    insecure_patterns = [
        'client_id = "abc123"',  # Hardcoded in source
        'CLIENT_SECRET = "secret123"',  # Hardcoded constant
        'config.json with credentials',  # Committed to git
    ]
    
    # Run static analysis to detect these patterns
    assert not credentials_in_source_code()
```

### Token Storage Security

**Attack**: Token Theft from Insecure Storage
**Impact**: Attacker gains unauthorized access to user resources

```python
def test_token_storage_security():
    """
    Tokens must be stored securely
    """
    
    # ✅ SECURE: Encrypted storage
    # - Server-side: Encrypted database, secure session storage
    # - Client-side: Secure storage APIs (iOS Keychain, Android KeyStore)
    
    # ❌ INSECURE: NEVER store tokens in:
    insecure_locations = [
        'localStorage',  # Vulnerable to XSS in browsers
        'sessionStorage',  # Vulnerable to XSS in browsers
        'cookies without HttpOnly+Secure flags',
        'plain text files',
        'application logs',
    ]
    
    # Test: Verify tokens are encrypted at rest
    stored_token = secure_storage.get('access_token')
    assert is_encrypted(stored_token)
    
    # Test: Verify tokens are not in logs
    log_content = read_application_logs()
    assert 'access_token' not in log_content
    assert not contains_jwt_pattern(log_content)
```

### Authorization Code Single Use

**Attack**: Authorization Code Replay
**Impact**: Reused codes can compromise security

```python
def test_authorization_code_single_use():
    """
    Authorization codes MUST be used only once
    """
    
    # Simulate receiving an authorization code
    auth_code = 'one_time_code_xyz'
    
    # First use: Should succeed
    tokens = oauth_client.exchange_code(auth_code)
    assert tokens['access_token'] is not None
    
    # Second use: Should fail
    with pytest.raises(InvalidGrantError):
        oauth_client.exchange_code(auth_code)
    
    # Implementation note: Track used codes in database/cache
    # Reject if code was already used
```

### Scope Restriction (Principle of Least Privilege)

**Attack**: Excessive Permissions
**Impact**: Compromised tokens have more access than needed

```python
def test_scope_restriction():
    """
    Request only the minimum scopes needed
    """
    
    # ✅ SECURE: Request specific, limited scopes
    required_scopes = ['read:calendar', 'write:calendar']
    
    # ❌ INSECURE: Requesting overly broad permissions
    excessive_scopes = [
        'admin',  # Full admin access when only calendar needed
        '*',  # Wildcard/all permissions
        'read write delete admin',  # Everything when only read needed
    ]
    
    # Test: Verify only required scopes requested
    auth_request = build_authorization_request()
    requested_scopes = parse_scopes(auth_request)
    
    assert set(requested_scopes) == set(required_scopes)
    assert not any(scope in requested_scopes for scope in excessive_scopes)
```

### Token Expiration Handling

```python
def test_token_expiration_strategy():
    """
    Properly handle expired tokens
    """
    
    # Strategy 1: Check expiration before use
    def use_token_with_precheck():
        token = get_stored_token()
        if is_token_expired(token):
            token = refresh_token()
        return make_api_call(token)
    
    # Strategy 2: Handle 401 and retry
    def use_token_with_retry():
        try:
            return make_api_call(get_stored_token())
        except TokenExpiredError:
            new_token = refresh_token()
            return make_api_call(new_token)
    
    # Test both strategies work
    assert use_token_with_precheck() is not None
    assert use_token_with_retry() is not None
```

---

## Implementation Guidelines for Coding Agents

### When Analyzing a Codebase

As a coding agent tasked with implementing or reviewing OAuth, follow this systematic approach:

#### Phase 1: Discovery and Analysis

**1. Identify the OAuth Flow Type**

```
LOOK FOR:
- Authorization endpoints being called
- Presence of PKCE parameters (code_challenge, code_verifier)
- Client credential storage (client_id, client_secret)
- Token exchange mechanisms

DETERMINE:
- Is this a public client (SPA, mobile, native) or confidential client (server-side)?
- Is PKCE implemented? (MANDATORY for public clients as of 2025)
- Which grant type is being used?

RECOMMENDATIONS:
✅ Authorization Code + PKCE: Use for ALL applications
❌ Implicit Flow: Deprecated, suggest migration to PKCE
❌ Password Grant: Deprecated, suggest alternative
✅ Client Credentials: OK for machine-to-machine only
```

**2. Map the OAuth Flow**

```
CREATE A FLOW DIAGRAM:

Step 1: /auth/login route
  ├─ Generates state
  ├─ Generates code_verifier (PKCE)
  ├─ Calculates code_challenge
  └─ Redirects to authorization server

Step 2: Authorization server
  ├─ User authenticates
  └─ Redirects to /auth/callback with code

Step 3: /auth/callback route
  ├─ Validates state parameter
  ├─ Exchanges code + code_verifier for tokens
  └─ Stores tokens securely

Step 4: Protected resource access
  ├─ Uses access_token
  ├─ Handles 401 errors
  └─ Refreshes token if needed

IDENTIFY GAPS:
- Missing steps
- Insecure implementations
- Missing error handling
```

#### Phase 2: Security Assessment

**3. Security Checklist**

Run through this checklist for the codebase:

```
CREDENTIAL SECURITY:
[ ] Client credentials NOT in source code
[ ] Client credentials loaded from secure storage (env vars, secret manager)
[ ] redirect_uri matches exactly what's registered
[ ] redirect_uri validation prevents open redirects

STATE PARAMETER (CSRF Protection):
[ ] State parameter is generated (cryptographically random)
[ ] State is unique per request
[ ] State has sufficient entropy (≥128 bits)
[ ] State is validated on callback
[ ] State mismatch is rejected with error
[ ] State is single-use (cleared after validation)

PKCE (Public Clients):
[ ] code_verifier generated (43-128 chars)
[ ] code_verifier is cryptographically random
[ ] code_challenge derived using S256 (SHA-256)
[ ] code_challenge sent in authorization request
[ ] code_verifier sent in token exchange
[ ] NO usage of 'plain' method (deprecated)

TOKEN HANDLING:
[ ] Tokens stored securely (encrypted at rest)
[ ] Tokens NOT in localStorage/sessionStorage (browsers)
[ ] Tokens NOT in logs
[ ] Tokens NOT transmitted in URLs
[ ] Access token used in Authorization header (Bearer)
[ ] Refresh token stored separately and securely

TOKEN LIFECYCLE:
[ ] Token expiration checked before use OR
[ ] 401 errors handled with token refresh
[ ] Refresh token used to get new access token
[ ] New refresh token replaces old (if provided)
[ ] Old refresh token kept if new one not provided
[ ] Re-authentication triggered if refresh fails

AUTHORIZATION CODE:
[ ] Code used only once
[ ] Code validation before exchange
[ ] Used codes tracked to prevent replay

SCOPE MANAGEMENT:
[ ] Minimum required scopes requested
[ ] No wildcards or admin scopes unless necessary
[ ] Scope validation in API calls

ERROR HANDLING:
[ ] User denial handled gracefully
[ ] Network errors handled gracefully
[ ] Invalid code errors handled
[ ] Token expired errors handled
[ ] Refresh token expired triggers re-auth
[ ] No sensitive data in error messages
```

#### Phase 3: Test Strategy

**4. Determine Testing Approach**

```
FOR EACH COMPONENT, DECIDE:

Component: Authorization Request (/auth/login)
├─ Unit Tests:
│  ├─ Returns 3xx redirect
│  ├─ Includes correct parameters (client_id, redirect_uri, state, code_challenge)
│  ├─ State is unique per request
│  └─ PKCE parameters are correct
├─ Integration Tests:
│  └─ Full redirect to authorization server works
└─ Security Tests:
   ├─ Credentials not exposed
   └─ State has high entropy

Component: Callback Handler (/auth/callback)
├─ Unit Tests:
│  ├─ State validation (match/mismatch)
│  ├─ Error parameter handling
│  ├─ Missing parameter handling
│  └─ Token storage after successful exchange
├─ Integration Tests:
│  └─ Complete flow with mock authorization server
└─ Security Tests:
   ├─ State mismatch rejected
   └─ Authorization code replay prevented

Component: Token Exchange (Internal function)
├─ Unit Tests:
│  ├─ Correct parameters sent (code, code_verifier, client_id, client_secret)
│  ├─ Success response parsed correctly
│  ├─ Error response handled
│  └─ Tokens stored in secure location
└─ Security Tests:
   ├─ Client secret in POST body (not URL)
   └─ HTTPS enforced

Component: API Calls (Using access token)
├─ Unit Tests:
│  ├─ Token included in Authorization header
│  ├─ 401 triggers refresh
│  ├─ Successful refresh retries request
│  └─ Failed refresh triggers re-auth
└─ Integration Tests:
   └─ Token refresh flow works end-to-end

Component: Token Refresh (Internal function)
├─ Unit Tests:
│  ├─ Refresh token sent correctly
│  ├─ New access token stored
│  ├─ New refresh token stored (if provided)
│  ├─ Old refresh token kept (if not provided)
│  └─ Error handling for expired refresh token
└─ Security Tests:
   └─ Refresh token stored securely
```

#### Phase 4: Test Implementation

**5. Generate Test Code**

For each component identified, generate appropriate tests:

```
TEMPLATE FOR UNIT TESTS:

def test_{component}_{behavior}():
    """
    Test that {component} correctly {behavior}
    
    Security consideration: {why this matters}
    """
    # Arrange: Set up test conditions
    # Act: Execute the code
    # Assert: Verify expected outcome
    pass

EXAMPLE:

def test_authorization_request_includes_pkce_challenge():
    """
    Test that authorization request includes PKCE code_challenge
    
    Security consideration: PKCE prevents authorization code 
    interception attacks in public clients
    """
    # Arrange
    with client.session_transaction() as session:
        pass  # Clear any existing state
    
    # Act
    response = client.get('/auth/login')
    
    # Assert
    location = response.headers.get('Location')
    assert 'code_challenge=' in location
    assert 'code_challenge_method=S256' in location
    
    # Verify challenge stored for later validation
    with client.session_transaction() as session:
        assert 'pkce_code_verifier' in session
```

**6. Test Data Management**

```
SECURE TEST DATA:
- Use environment variables for test credentials
- Never commit real OAuth credentials to version control
- Use OAuth provider's sandbox/test environment when available
- Create dedicated test accounts for integration tests

TEST DATA STRUCTURE:

# test_config.py
TEST_OAUTH_CONFIG = {
    'client_id': os.getenv('TEST_OAUTH_CLIENT_ID', 'test_client_id'),
    'client_secret': os.getenv('TEST_OAUTH_CLIENT_SECRET', 'test_secret'),
    'redirect_uri': 'http://localhost:5000/auth/callback',
    'authorization_endpoint': 'https://test-auth.example.com/authorize',
    'token_endpoint': 'https://test-auth.example.com/token',
    'scopes': ['read:user', 'read:calendar'],
}

MOCK DATA PATTERNS:

MOCK_TOKEN_RESPONSE = {
    'access_token': 'mock_access_token_' + random_string(),
    'token_type': 'Bearer',
    'expires_in': 3600,
    'refresh_token': 'mock_refresh_token_' + random_string(),
    'scope': 'read:user read:calendar'
}

MOCK_USER_RESPONSE = {
    'id': 'test_user_123',
    'email': 'test@example.com',
    'name': 'Test User'
}
```

---

## Common Pitfalls to Avoid

### Anti-Pattern 1: Storing Tokens in localStorage (Browser Apps)

```javascript
// ❌ INSECURE - Vulnerable to XSS attacks
localStorage.setItem('access_token', token);

// ✅ SECURE - Use httpOnly cookies or secure backend storage
// Token should be stored server-side and accessed via session
```

**Why it's wrong**: XSS attacks can read localStorage. If any third-party script on your page is compromised, tokens are exposed.

**What to do instead**: Store tokens server-side, use httpOnly+Secure cookies for session management, or use backend-for-frontend (BFF) pattern.

### Anti-Pattern 2: Same State Value for All Requests

```python
# ❌ INSECURE - Predictable state
STATE = f"user_{user_id}"

# ✅ SECURE - Cryptographically random state
import secrets
state = secrets.token_urlsafe(32)
```

**Why it's wrong**: Attacker can predict state value and perform CSRF attacks.

**What to do instead**: Generate cryptographically random state for each OAuth flow initiation.

### Anti-Pattern 3: Not Validating State on Callback

```python
# ❌ INSECURE - No state validation
@app.route('/callback')
def callback():
    code = request.args.get('code')
    # Missing: state validation
    tokens = exchange_code(code)

# ✅ SECURE - Validate state
@app.route('/callback')
def callback():
    received_state = request.args.get('state')
    stored_state = session.get('oauth_state')
    
    if not received_state or received_state != stored_state:
        return "Invalid state parameter", 403
    
    code = request.args.get('code')
    tokens = exchange_code(code)
```

**Why it's wrong**: Opens door to CSRF attacks where attacker can link victim's account to attacker's OAuth account.

### Anti-Pattern 4: Using Implicit Flow (2025)

```
# ❌ DEPRECATED - Implicit Flow
GET /authorize?response_type=token&client_id=...

# ✅ SECURE - Authorization Code + PKCE
GET /authorize?response_type=code&code_challenge=...&client_id=...
```

**Why it's wrong**: Implicit flow is deprecated due to security vulnerabilities (tokens in browser history, no client authentication).

**What to do instead**: Use Authorization Code flow with PKCE for ALL client types.

### Anti-Pattern 5: Client Secret in Frontend Code

```javascript
// ❌ INSECURE - Client secret exposed
const config = {
    clientId: 'abc123',
    clientSecret: 'secret_xyz'  // NEVER do this!
};

// ✅ SECURE - No client secret in public clients
// Use PKCE instead, or proxy through backend
const config = {
    clientId: 'abc123',
    // No client secret - using PKCE
    usePKCE: true
};
```

**Why it's wrong**: Anyone can view frontend source code and extract the secret.

**What to do instead**: Public clients (SPAs, mobile) should NOT have secrets. Use PKCE. Only confidential clients (backend servers) can safely use secrets.

### Anti-Pattern 6: Not Handling Token Expiration

```python
# ❌ INSECURE - No expiration handling
def get_user_data():
    token = get_stored_token()
    return api_call(token)  # Will fail if token expired

# ✅ SECURE - Handle expiration
def get_user_data():
    token = get_stored_token()
    
    if is_expired(token):
        token = refresh_token()
    
    try:
        return api_call(token)
    except TokenExpiredError:
        token = refresh_token()
        return api_call(token)
```

**Why it's wrong**: Breaks user experience and may leave app in broken state.

### Anti-Pattern 7: Logging Tokens

```python
# ❌ INSECURE - Token in logs
logger.info(f"User authenticated with token: {access_token}")

# ✅ SECURE - Never log sensitive data
logger.info(f"User authenticated successfully")
# Or log only a hash/prefix
logger.debug(f"Token prefix: {access_token[:10]}...")
```

**Why it's wrong**: Log files may be compromised, shared, or stored insecurely.

### Anti-Pattern 8: Accepting Any Redirect URI

```python
# ❌ INSECURE - No redirect URI validation
redirect_uri = request.args.get('redirect_uri')
# Directly use without validation

# ✅ SECURE - Exact match validation
ALLOWED_REDIRECT_URIS = [
    'https://myapp.com/auth/callback',
    'https://myapp.com/auth/callback-alt'
]

redirect_uri = request.args.get('redirect_uri')
if redirect_uri not in ALLOWED_REDIRECT_URIS:
    return "Invalid redirect URI", 400
```

**Why it's wrong**: Attacker can redirect authorization codes to their own server.

### Anti-Pattern 9: Reusing Authorization Codes

```python
# ❌ INSECURE - No code replay prevention
def exchange_code(code):
    tokens = call_token_endpoint(code)
    return tokens  # Code can be reused!

# ✅ SECURE - Track used codes
used_codes = set()  # Or database/cache

def exchange_code(code):
    if code in used_codes:
        raise CodeReplayError("Code already used")
    
    tokens = call_token_endpoint(code)
    used_codes.add(code)
    return tokens
```

**Why it's wrong**: Compromised codes could be reused by attackers.

---

## Testing Tools and Frameworks

### Recommended Testing Libraries

#### Python
```python
# Unit testing
import pytest
import unittest
from unittest.mock import Mock, patch, MagicMock

# HTTP mocking
import responses  # For mocking HTTP requests
import httpretty  # Alternative HTTP mocking

# Integration testing
import requests
from flask.testing import FlaskClient  # For Flask apps
from django.test import Client  # For Django apps

# Security testing
import hashlib
import secrets
```

#### JavaScript/TypeScript
```javascript
// Unit testing
import { describe, it, expect, jest } from '@jest/globals';
import { vi } from 'vitest';  // Alternative to Jest

// HTTP mocking
import nock from 'nock';
import fetchMock from 'jest-fetch-mock';

// Integration testing
import supertest from 'supertest';
import { chromium } from 'playwright';  // Browser automation

// Security
import crypto from 'crypto';
```

### Mock OAuth Server Setup

```python
# Using responses library
import responses

@responses.activate
def test_oauth_flow_with_mock_server():
    # Mock authorization endpoint
    responses.add(
        responses.GET,
        'https://oauth.provider.com/authorize',
        status=302,
        headers={
            'Location': 'http://localhost/callback?code=test_code&state=test_state'
        }
    )
    
    # Mock token endpoint
    responses.add(
        responses.POST,
        'https://oauth.provider.com/token',
        json={
            'access_token': 'mock_access_token',
            'token_type': 'Bearer',
            'expires_in': 3600,
            'refresh_token': 'mock_refresh_token'
        },
        status=200
    )
    
    # Run your OAuth flow
    result = perform_oauth_login()
    assert result['access_token'] == 'mock_access_token'
```

### Integration Test Helpers

```python
class OAuthTestHelper:
    """Helper class for OAuth integration tests"""
    
    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
    
    def simulate_authorization(self, user_email, scopes):
        """Simulate user granting authorization"""
        # In real tests, might use Selenium/Playwright
        # to actually interact with OAuth provider
        pass
    
    def generate_test_tokens(self):
        """Generate mock tokens for testing"""
        return {
            'access_token': f"test_access_{secrets.token_hex(16)}",
            'refresh_token': f"test_refresh_{secrets.token_hex(16)}",
            'expires_in': 3600,
            'token_type': 'Bearer'
        }
    
    def verify_pkce_flow(self, code_verifier, code_challenge):
        """Verify PKCE parameters are correct"""
        import hashlib
        import base64
        
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip('=')
        
        assert code_challenge == expected_challenge
        return True
```

---

## Decision Tree for Coding Agents

When encountering OAuth code, use this decision tree:

```
START: Analyzing OAuth Implementation
│
├─ Q: Is PKCE implemented?
│  ├─ NO → Is this a public client (SPA/mobile/native)?
│  │  ├─ YES → [CRITICAL] MUST implement PKCE
│  │  └─ NO → [RECOMMENDED] Should implement PKCE anyway
│  └─ YES → Verify PKCE is correct:
│     ├─ code_verifier: 43-128 chars, cryptographically random?
│     ├─ code_challenge: SHA-256 of verifier, base64url encoded?
│     ├─ code_challenge_method: S256 (not 'plain')?
│     └─ code_verifier sent in token exchange?
│
├─ Q: Is state parameter implemented?
│  ├─ NO → [CRITICAL] MUST implement state parameter
│  └─ YES → Verify state is secure:
│     ├─ Cryptographically random (≥32 chars)?
│     ├─ Unique per request?
│     ├─ Validated on callback?
│     ├─ Mismatch triggers error/rejection?
│     └─ Single-use (cleared after validation)?
│
├─ Q: Are credentials secure?
│  ├─ Check: client_id/client_secret in source code?
│  │  └─ YES → [CRITICAL] Move to secure storage
│  ├─ Check: Credentials loaded from environment/vault?
│  │  └─ NO → [CRITICAL] Implement secure loading
│  └─ Check: Credentials in logs?
│     └─ YES → [CRITICAL] Remove from logs
│
├─ Q: Are tokens stored securely?
│  ├─ Check: Tokens in localStorage/sessionStorage (browser)?
│  │  └─ YES → [CRITICAL] Move to httpOnly cookies or backend
│  ├─ Check: Tokens encrypted at rest?
│  │  └─ NO → [RECOMMENDED] Implement encryption
│  └─ Check: Tokens in logs?
│     └─ YES → [CRITICAL] Remove from logs
│
├─ Q: Is token expiration handled?
│  ├─ Check: Token expiration checked before use OR 401 handled?
│  │  └─ NO → [IMPORTANT] Implement expiration handling
│  ├─ Check: Refresh token flow implemented?
│  │  └─ NO → [IMPORTANT] Implement refresh flow
│  └─ Check: Re-authentication triggered on refresh failure?
│     └─ NO → [IMPORTANT] Implement re-auth trigger
│
├─ Q: Is redirect_uri validated?
│  ├─ Check: Exact match validation (no partial matching)?
│  │  └─ NO → [CRITICAL] Implement exact match
│  └─ Check: Open redirect vulnerabilities?
│     └─ YES → [CRITICAL] Fix redirect validation
│
├─ Q: Are scopes minimized?
│  ├─ Check: Only minimum required scopes requested?
│  │  └─ NO → [RECOMMENDED] Reduce scope requests
│  └─ Check: Wildcard or admin scopes used unnecessarily?
│     └─ YES → [RECOMMENDED] Use specific scopes
│
└─ Q: Is error handling comprehensive?
   ├─ Check: User denial handled gracefully?
   ├─ Check: Network errors handled?
   ├─ Check: Invalid code/token errors handled?
   └─ Check: No sensitive data in error messages?
      └─ NO to any → [IMPORTANT] Implement error handling

PRIORITY LEVELS:
[CRITICAL] - Security vulnerability, must fix immediately
[IMPORTANT] - Functionality or security issue, fix soon
[RECOMMENDED] - Best practice, improve when possible
```

---

## Test Coverage Goals

### Minimum Test Coverage

For OAuth implementations to be considered "tested," aim for:

```
UNIT TESTS:
✓ Authorization request generation (4+ tests)
  - Redirect response
  - State uniqueness
  - PKCE parameters
  - Scope inclusion

✓ Callback handling (6+ tests)
  - State validation (match)
  - State validation (mismatch)
  - Missing state
  - Missing code
  - Error parameter
  - Successful exchange

✓ Token exchange (5+ tests)
  - Successful exchange
  - Client credentials included
  - PKCE verifier included
  - Error handling
  - Token storage

✓ API calls with token (4+ tests)
  - Token in Authorization header
  - 401 handling
  - Automatic refresh
  - Refresh failure

✓ Token refresh (5+ tests)
  - Successful refresh
  - Replace access token
  - Replace/keep refresh token
  - Error handling
  - Re-authentication trigger

INTEGRATION TESTS:
✓ Complete OAuth flow (2+ tests)
  - Happy path
  - With token refresh

✓ Error scenarios (3+ tests)
  - User denial
  - Expired authorization code
  - Network errors

SECURITY TESTS:
✓ CSRF protection (3+ tests)
  - State uniqueness
  - State validation
  - State mismatch rejection

✓ Credential security (3+ tests)
  - No hardcoded credentials
  - Secure storage
  - No logging of sensitive data

✓ PKCE validation (3+ tests)
  - Verifier generation
  - Challenge derivation
  - S256 method used

TOTAL MINIMUM: 40+ tests
```

### Coverage Metrics

```
CODE COVERAGE TARGET:
- Unit tests: ≥80% of OAuth-related code
- Integration tests: 100% of critical paths
- Security tests: 100% of security controls

CRITICAL PATHS (Must be 100% covered):
- State parameter generation and validation
- PKCE implementation (if applicable)
- Token exchange
- Token refresh
- Credential loading
- Token storage
```

---

## Quick Reference: Test Checklist for Coding Agents

When implementing tests for OAuth, use this checklist:

### Pre-Implementation

- [ ] Identify OAuth flow type (Authorization Code, Client Credentials, etc.)
- [ ] Determine if client is public or confidential
- [ ] Verify PKCE is required (public clients) or recommended (confidential)
- [ ] Review OAuth provider's documentation for specific requirements
- [ ] Set up test environment (test credentials, mock server, etc.)

### Security Tests (Priority 1 - CRITICAL)

- [ ] State parameter is cryptographically random
- [ ] State parameter is unique per request
- [ ] State parameter is validated on callback
- [ ] State mismatch triggers error
- [ ] PKCE implemented (if public client)
- [ ] PKCE code_verifier is 43-128 chars
- [ ] PKCE code_challenge uses S256 method
- [ ] Client credentials NOT in source code
- [ ] Client credentials loaded securely
- [ ] Tokens NOT in localStorage (browsers)
- [ ] Tokens stored encrypted
- [ ] Tokens NOT in logs
- [ ] Redirect URI exact match validation
- [ ] Authorization codes used only once

### Functionality Tests (Priority 2 - IMPORTANT)

- [ ] Authorization request returns 3xx redirect
- [ ] Authorization request includes all required parameters
- [ ] Callback validates all parameters
- [ ] Callback handles missing/invalid parameters
- [ ] Token exchange sends correct parameters
- [ ] Token exchange handles success response
- [ ] Token exchange handles error response
- [ ] Tokens stored after successful exchange
- [ ] Access token used in API calls
- [ ] Token expiration detected
- [ ] Automatic token refresh implemented
- [ ] Refresh success updates tokens
- [ ] Refresh failure triggers re-authentication
- [ ] User denial handled gracefully
- [ ] Network errors handled gracefully

### Integration Tests (Priority 3 - VERIFY END-TO-END)

- [ ] Complete OAuth flow works
- [ ] OAuth flow with token refresh works
- [ ] Error scenarios handled correctly
- [ ] Multiple concurrent OAuth flows work
- [ ] OAuth flow works across browser redirects

### Code Quality

- [ ] Tests are independent (no shared state)
- [ ] Tests use descriptive names
- [ ] Tests include security rationale in comments
- [ ] Mocks/stubs are properly configured
- [ ] Test data is realistic
- [ ] Edge cases are covered

---

## Example Test Suite Structure

Here's a recommended structure for organizing OAuth tests:

```
tests/
├── unit/
│   ├── test_authorization_request.py
│   │   ├── test_generates_state_parameter()
│   │   ├── test_state_is_unique_per_request()
│   │   ├── test_generates_pkce_verifier()
│   │   ├── test_calculates_pkce_challenge()
│   │   └── test_includes_required_scopes()
│   │
│   ├── test_callback_handler.py
│   │   ├── test_validates_state_match()
│   │   ├── test_rejects_state_mismatch()
│   │   ├── test_handles_missing_state()
│   │   ├── test_handles_missing_code()
│   │   ├── test_handles_error_parameter()
│   │   └── test_exchanges_code_for_token()
│   │
│   ├── test_token_exchange.py
│   │   ├── test_includes_client_credentials()
│   │   ├── test_includes_pkce_verifier()
│   │   ├── test_handles_success_response()
│   │   ├── test_handles_error_response()
│   │   └── test_stores_tokens_securely()
│   │
│   ├── test_token_refresh.py
│   │   ├── test_uses_refresh_token()
│   │   ├── test_updates_access_token()
│   │   ├── test_updates_refresh_token_if_provided()
│   │   ├── test_keeps_refresh_token_if_not_provided()
│   │   └── test_handles_refresh_failure()
│   │
│   └── test_api_client.py
│       ├── test_includes_bearer_token()
│       ├── test_handles_401_error()
│       ├── test_automatic_refresh_on_401()
│       └── test_retries_after_refresh()
│
├── integration/
│   ├── test_full_oauth_flow.py
│   │   ├── test_complete_authorization_code_flow()
│   │   ├── test_oauth_flow_with_token_refresh()
│   │   └── test_oauth_flow_with_user_denial()
│   │
│   └── test_oauth_error_scenarios.py
│       ├── test_expired_authorization_code()
│       ├── test_network_error_during_token_exchange()
│       └── test_authorization_server_unavailable()
│
├── security/
│   ├── test_csrf_protection.py
│   │   ├── test_state_uniqueness()
│   │   ├── test_state_entropy()
│   │   ├── test_state_validation()
│   │   └── test_state_single_use()
│   │
│   ├── test_pkce_security.py
│   │   ├── test_verifier_generation()
│   │   ├── test_challenge_derivation()
│   │   ├── test_uses_s256_method()
│   │   └── test_verifier_in_token_exchange()
│   │
│   ├── test_credential_security.py
│   │   ├── test_no_credentials_in_source()
│   │   ├── test_credentials_loaded_securely()
│   │   └── test_no_credentials_in_logs()
│   │
│   └── test_token_security.py
│       ├── test_tokens_encrypted_at_rest()
│       ├── test_no_tokens_in_browser_storage()
│       ├── test_no_tokens_in_logs()
│       └── test_redirect_uri_validation()
│
├── helpers/
│   ├── oauth_test_helper.py
│   ├── mock_oauth_server.py
│   └── test_data_generator.py
│
└── conftest.py  # Pytest fixtures and configuration
```

---

## Summary: Key Takeaways for Coding Agents

When you're tasked with testing or implementing OAuth:

1. **Security First**: OAuth vulnerabilities can compromise not just your app, but the services your users connect to. Prioritize security tests.

2. **PKCE is Mandatory**: As of 2025 standards (RFC 9700), PKCE is required for public clients and recommended for all clients.

3. **State Parameter is Critical**: Always implement and validate state parameter to prevent CSRF attacks.

4. **Test Beyond Happy Path**: Error handling and security edge cases are where vulnerabilities hide.

5. **Never Trust, Always Verify**:
   - Verify state matches
   - Verify redirect URI is exact
   - Verify tokens before use
   - Verify credentials are secure

6. **Unit Test with Mocks, Integration Test with Care**: Mock OAuth providers in unit tests, but also test the full flow in integration tests.

7. **Documentation**: Include security rationale in test comments so future developers understand why each test exists.

8. **Continuous Review**: OAuth security best practices evolve. Stay updated with RFC changes and security advisories.

---

## Additional Resources

- **RFC 9700**: OAuth 2.0 Security Best Current Practice (January 2025)
- **RFC 7636**: Proof Key for Code Exchange (PKCE)
- **RFC 6749**: OAuth 2.0 Authorization Framework
- **OWASP**: OAuth 2.0 Security Cheat Sheet
- **OAuth.net**: Official OAuth documentation and resources

---

*This guide is designed for coding agents (like Claude Code) to systematically analyze, test, and secure OAuth implementations. Follow this guide when reviewing codebases, implementing new OAuth flows, or auditing existing implementations.*