"""
OAuth flows for Linear, GitHub, and Slack.
"""
import os
import httpx
from urllib.parse import urlencode
from typing import Optional

# OAuth Configuration (from environment)
def get_oauth_config():
    return {
        'linear': {
            'client_id': os.environ.get('LINEAR_CLIENT_ID'),
            'client_secret': os.environ.get('LINEAR_CLIENT_SECRET'),
            'authorize_url': 'https://linear.app/oauth/authorize',
            'token_url': 'https://api.linear.app/oauth/token',
            'scopes': ['read', 'write'],
        },
        'github': {
            'client_id': os.environ.get('GITHUB_CLIENT_ID'),
            'client_secret': os.environ.get('GITHUB_CLIENT_SECRET'),
            'authorize_url': 'https://github.com/login/oauth/authorize',
            'token_url': 'https://github.com/login/oauth/access_token',
            'scopes': ['repo', 'read:user'],
        },
        'slack': {
            'client_id': os.environ.get('SLACK_CLIENT_ID'),
            'client_secret': os.environ.get('SLACK_CLIENT_SECRET'),
            'authorize_url': 'https://slack.com/oauth/v2/authorize',
            'token_url': 'https://slack.com/api/oauth.v2.access',
            'scopes': ['channels:history', 'channels:read', 'groups:read', 'users:read'],
        },
    }


def get_authorize_url(provider: str, redirect_uri: str, state: str) -> str:
    """Generate OAuth authorization URL."""
    config = get_oauth_config()[provider]

    params = {
        'client_id': config['client_id'],
        'redirect_uri': redirect_uri,
        'state': state,
    }

    if provider == 'slack':
        params['scope'] = ','.join(config['scopes'])
    else:
        params['scope'] = ' '.join(config['scopes'])

    if provider == 'linear':
        params['response_type'] = 'code'

    return f"{config['authorize_url']}?{urlencode(params)}"


async def exchange_code_for_token(provider: str, code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access token."""
    config = get_oauth_config()[provider]

    data = {
        'client_id': config['client_id'],
        'client_secret': config['client_secret'],
        'code': code,
        'redirect_uri': redirect_uri,
    }

    if provider == 'github':
        data['accept'] = 'application/json'
    elif provider == 'linear':
        data['grant_type'] = 'authorization_code'

    headers = {'Accept': 'application/json'}

    async with httpx.AsyncClient() as client:
        response = await client.post(config['token_url'], data=data, headers=headers)

        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")

        return response.json()


async def get_user_info(provider: str, access_token: str) -> dict:
    """Get user/workspace info from the provider."""
    async with httpx.AsyncClient() as client:
        if provider == 'linear':
            response = await client.post(
                'https://api.linear.app/graphql',
                headers={'Authorization': access_token, 'Content-Type': 'application/json'},
                json={'query': '{ viewer { id name email } organization { id name } }'}
            )
            data = response.json()
            return {
                'user_id': data.get('data', {}).get('viewer', {}).get('id'),
                'user_name': data.get('data', {}).get('viewer', {}).get('name'),
                'org_name': data.get('data', {}).get('organization', {}).get('name'),
            }

        elif provider == 'github':
            response = await client.get(
                'https://api.github.com/user',
                headers={'Authorization': f'Bearer {access_token}'}
            )
            data = response.json()
            return {
                'user_id': str(data.get('id')),
                'user_name': data.get('login'),
                'name': data.get('name'),
            }

        elif provider == 'slack':
            response = await client.get(
                'https://slack.com/api/auth.test',
                headers={'Authorization': f'Bearer {access_token}'}
            )
            data = response.json()
            return {
                'team_id': data.get('team_id'),
                'team_name': data.get('team'),
                'user_id': data.get('user_id'),
            }

    return {}
