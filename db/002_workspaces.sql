-- Migration: 002_workspaces.sql
-- Multi-tenant workspace support for ScopeDocs MVP
--
-- Design decisions (from team discussion):
-- 1. Workspace-based model (not single user)
-- 2. Simple invite flow for MVP (no OAuth auto-join yet)
-- 3. Store external org IDs for future auto-join feature

-- =============================================================================
-- Table: workspaces
-- =============================================================================
-- Each workspace represents a team/org using ScopeDocs together.
-- Members share access to synced data from connected integrations.

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Display name (e.g., "ScopeDocs Team", "Acme Corp")
    name TEXT NOT NULL,
    
    -- Slug for URLs (e.g., "scopedocs", "acme-corp")
    slug TEXT NOT NULL UNIQUE,
    
    -- External org/workspace identifiers (for future OAuth auto-join)
    github_org_id TEXT,          -- GitHub organization ID
    slack_team_id TEXT,          -- Slack workspace ID (e.g., "T0123456789")
    linear_org_id TEXT,          -- Linear organization ID
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Table: workspace_members
-- =============================================================================
-- Links users to workspaces with roles.

CREATE TABLE IF NOT EXISTS workspace_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Role: 'owner' | 'admin' | 'member'
    role TEXT NOT NULL DEFAULT 'member',
    
    -- When they joined
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    UNIQUE(workspace_id, user_id)
);

-- =============================================================================
-- Table: workspace_invites
-- =============================================================================
-- Simple email invite flow for MVP.

CREATE TABLE IF NOT EXISTS workspace_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    
    -- Who sent the invite
    invited_by UUID NOT NULL REFERENCES users(id),
    
    -- Email of invitee
    email TEXT NOT NULL,
    
    -- Invite token (for the link)
    token TEXT NOT NULL UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex'),
    
    -- Status: 'pending' | 'accepted' | 'expired'
    status TEXT NOT NULL DEFAULT 'pending',
    
    -- Expiration (7 days by default)
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '7 days',
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Prevent duplicate invites to same email for same workspace
    UNIQUE(workspace_id, email)
);

-- =============================================================================
-- Update existing tables to use workspace_id
-- =============================================================================

-- Add workspace_id to user_integrations (OAuth tokens are per-workspace)
ALTER TABLE user_integrations 
ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

-- Add workspace_id to synced data tables
ALTER TABLE slack_messages 
ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

ALTER TABLE github_prs 
ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

ALTER TABLE linear_issues 
ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

ALTER TABLE code_chunks 
ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

-- =============================================================================
-- Indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace 
ON workspace_members(workspace_id);

CREATE INDEX IF NOT EXISTS idx_workspace_members_user 
ON workspace_members(user_id);

CREATE INDEX IF NOT EXISTS idx_workspace_invites_token 
ON workspace_invites(token);

CREATE INDEX IF NOT EXISTS idx_workspace_invites_email 
ON workspace_invites(email);

-- Indexes for filtering by workspace
CREATE INDEX IF NOT EXISTS idx_user_integrations_workspace 
ON user_integrations(workspace_id);

CREATE INDEX IF NOT EXISTS idx_slack_messages_workspace 
ON slack_messages(workspace_id);

CREATE INDEX IF NOT EXISTS idx_github_prs_workspace 
ON github_prs(workspace_id);

CREATE INDEX IF NOT EXISTS idx_linear_issues_workspace 
ON linear_issues(workspace_id);

-- =============================================================================
-- Row Level Security (RLS)
-- =============================================================================
-- Enable RLS so users can only see data from their workspaces.

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE slack_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE github_prs ENABLE ROW LEVEL SECURITY;
ALTER TABLE linear_issues ENABLE ROW LEVEL SECURITY;

-- Policy: Users can see workspaces they're members of
CREATE POLICY "Users see own workspaces" ON workspaces
FOR SELECT USING (
    id IN (SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid())
);

-- Policy: Users can see their own membership records
CREATE POLICY "Users see own memberships" ON workspace_members
FOR SELECT USING (user_id = auth.uid());

-- Policy: Workspace members can see data from their workspaces
CREATE POLICY "Members see workspace data" ON slack_messages
FOR SELECT USING (
    workspace_id IN (SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid())
);

CREATE POLICY "Members see workspace PRs" ON github_prs
FOR SELECT USING (
    workspace_id IN (SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid())
);

CREATE POLICY "Members see workspace issues" ON linear_issues
FOR SELECT USING (
    workspace_id IN (SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid())
);

-- =============================================================================
-- Triggers for updated_at
-- =============================================================================

CREATE TRIGGER update_workspaces_updated_at
    BEFORE UPDATE ON workspaces
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
