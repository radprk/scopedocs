# Multi-Tenant Design for ScopeDocs

## MVP Approach (Agreed)

✅ **Workspace-based model** (not single user)  
✅ **Simple invite flow** (owner invites by email)  
⏳ **OAuth auto-join** (future feature, not MVP)

---

## Data Model

```
┌─────────────────────────────────────────────────────────────┐
│                        WORKSPACES                           │
│  id | name | slug | github_org_id | slack_team_id | ...    │
└─────────────────────────────────────────────────────────────┘
         │
         │ 1:many
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    WORKSPACE_MEMBERS                        │
│  workspace_id | user_id | role (owner/admin/member)        │
└─────────────────────────────────────────────────────────────┘
         │
         │ workspace_id FK
         ▼
┌─────────────────────────────────────────────────────────────┐
│               ALL DATA TABLES (scoped by workspace)         │
│  user_integrations | slack_messages | github_prs | ...     │
│  Each has: workspace_id column                              │
└─────────────────────────────────────────────────────────────┘
```

---

## User Flows

### 1. Sign Up (New User, Creates Workspace)

```
User signs up via email/Google
    ↓
Create workspace (name: "My Team", slug: "my-team")
    ↓
Add user as workspace_member with role='owner'
    ↓
Redirect to connect integrations (Slack/GitHub/Linear)
```

### 2. Join via Invite (Existing Workspace)

```
Owner sends invite to team@example.com
    ↓
Invite created: workspace_invites { email, token, expires_at }
    ↓
Invitee clicks link: /invite/{token}
    ↓
If logged in: Add to workspace_members
If not: Sign up first, then add
```

### 3. Future: OAuth Auto-Join

```
User connects Slack → we get slack_team_id
    ↓
Check: Does workspace exist with this slack_team_id?
    ↓
Yes: Auto-add user as member
No: Create new workspace (or prompt to create)
```

---

## Tables Summary

| Table | Purpose |
|-------|---------|
| `workspaces` | Team/org container |
| `workspace_members` | User ↔ Workspace link + role |
| `workspace_invites` | Email invite tokens |
| `user_integrations` | OAuth tokens (per workspace) |
| `slack_messages` | Synced Slack data (per workspace) |
| `github_prs` | Synced GitHub data (per workspace) |
| `linear_issues` | Synced Linear data (per workspace) |

---

## Security: Row Level Security (RLS)

All tables have RLS enabled. Users can only query data from workspaces they belong to.

```sql
-- Example policy
CREATE POLICY "Members see workspace data" ON slack_messages
FOR SELECT USING (
    workspace_id IN (
        SELECT workspace_id FROM workspace_members 
        WHERE user_id = auth.uid()
    )
);
```

---

## API Changes Needed

### New Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /workspaces` | Create workspace |
| `GET /workspaces` | List user's workspaces |
| `POST /workspaces/{id}/invite` | Send email invite |
| `POST /invite/{token}/accept` | Accept invite |
| `GET /workspaces/{id}/members` | List members |

### Updated Endpoints

All data endpoints now require `workspace_id` context:

```
GET /sync/slack → GET /workspaces/{id}/sync/slack
GET /context → GET /workspaces/{id}/context
```

---

## Migration Path

1. **Run migration**: `db/002_workspaces.sql`
2. **Create default workspace** for existing data
3. **Update API** to pass workspace_id
4. **Update frontend** to select/display workspace

---

## Addressing Team Concerns

| Concern | Solution |
|---------|----------|
| "User in multiple GitHub orgs" | Each workspace stores one set of org IDs; user picks which to connect |
| "Contractors auto-joined wrongly" | Auto-join is future; MVP uses explicit invites |
| "OAuth disconnect handling" | Integration stays, just shows "disconnected" status |
| "Future pricing (per seat)" | workspace_members table makes seat counting easy |

---

## File: `db/002_workspaces.sql`

Ready to run. Creates all tables and RLS policies.
