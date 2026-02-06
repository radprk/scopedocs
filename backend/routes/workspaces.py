"""Workspace management routes."""

from fastapi import APIRouter, HTTPException

from backend.storage.postgres import list_workspaces, create_workspace, get_workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("")
async def api_list_workspaces():
    """List all workspaces."""
    workspaces = await list_workspaces()
    for w in workspaces:
        w['id'] = str(w['id'])
        if w.get('created_at'):
            w['created_at'] = w['created_at'].isoformat()
    return {"workspaces": workspaces}


@router.get("/{workspace_id}")
async def api_get_workspace(workspace_id: str):
    """Get a workspace by ID."""
    workspace = await get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace['id'] = str(workspace['id'])
    if workspace.get('created_at'):
        workspace['created_at'] = workspace['created_at'].isoformat()
    return workspace


@router.post("")
async def api_create_workspace(data: dict):
    """Create a new workspace."""
    name = data.get("name", "").strip()
    slug = data.get("slug", "").strip()
    
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    
    if not slug:
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
    
    try:
        workspace = await create_workspace(name, slug)
        workspace['id'] = str(workspace['id'])
        if workspace.get('created_at'):
            workspace['created_at'] = workspace['created_at'].isoformat()
        return workspace
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail=f"Workspace with slug '{slug}' already exists")
        raise HTTPException(status_code=500, detail=str(e))
