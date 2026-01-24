from datetime import datetime
from typing import Optional, Dict, Any
import os
import json
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from backend.models import IntegrationToken
from backend.storage.postgres import (
    upsert_integration_token,
    get_integration_token as pg_get_integration_token,
)


async def store_integration_token(token: IntegrationToken) -> None:
    """Store or update an integration token in PostgreSQL."""
    await upsert_integration_token(token.model_dump())


async def get_integration_token(integration: str, workspace_id: str) -> Optional[IntegrationToken]:
    """Get an integration token from PostgreSQL."""
    record = await pg_get_integration_token(integration, workspace_id)
    if record:
        return IntegrationToken(**record)
    return None


def load_integration_secret(secret_name: str) -> Optional[Dict[str, Any]]:
    """Load secrets from env or AWS Secrets Manager based on config."""
    secret_manager = os.environ.get('SECRET_MANAGER', 'env').lower()
    if secret_manager == 'aws':
        secret_id = os.environ.get(secret_name)
        if not secret_id:
            return None
        client = boto3.client('secretsmanager')
        try:
            response = client.get_secret_value(SecretId=secret_id)
        except (BotoCoreError, ClientError):
            return None
        secret_string = response.get('SecretString')
        if not secret_string:
            return None
        try:
            return json.loads(secret_string)
        except json.JSONDecodeError:
            return {'value': secret_string}
    return None


def load_oauth_credentials(integration: str) -> Dict[str, Optional[str]]:
    """Load OAuth credentials from env or secrets manager."""
    env_prefix = integration.upper()
    client_id = os.environ.get(f"{env_prefix}_CLIENT_ID")
    client_secret = os.environ.get(f"{env_prefix}_CLIENT_SECRET")

    secret_data = load_integration_secret(f"{env_prefix}_OAUTH_SECRET")
    if secret_data:
        client_id = client_id or secret_data.get('client_id')
        client_secret = client_secret or secret_data.get('client_secret')

    return {
        'client_id': client_id,
        'client_secret': client_secret,
    }


def build_token_from_env(integration: str, workspace_id: str) -> Optional[IntegrationToken]:
    """Fallback token creation when tokens are stored in env."""
    env_prefix = integration.upper()
    access_token = os.environ.get(f"{env_prefix}_ACCESS_TOKEN")
    refresh_token = os.environ.get(f"{env_prefix}_REFRESH_TOKEN")
    if not access_token:
        return None
    expires_at = os.environ.get(f"{env_prefix}_TOKEN_EXPIRES_AT")
    parsed_expires = None
    if expires_at:
        try:
            parsed_expires = datetime.fromisoformat(expires_at)
        except ValueError:
            parsed_expires = None
    return IntegrationToken(
        integration=integration,
        workspace_id=workspace_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=parsed_expires,
    )
