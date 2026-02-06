"""Code indexing routes."""

import uuid
import hashlib
from fastapi import APIRouter, HTTPException
import httpx

from backend.integrations.auth import get_integration_token
from backend.storage.postgres import get_pool

router = APIRouter(prefix="/api/index", tags=["indexing"])


@router.post("/repo")
async def api_index_repo(data: dict):
    """Index a GitHub repository for code search."""
    workspace_id = data.get("workspace_id")
    repo_full_name = data.get("repo_full_name")
    branch = data.get("branch", "main")
    
    if not workspace_id or not repo_full_name:
        raise HTTPException(status_code=400, detail="workspace_id and repo_full_name required")
    
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            }
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch repo tree: {response.text}"
            )
        
        tree_data = response.json()
        
        indexable_extensions = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java'}
        files_to_index = [
            item for item in tree_data.get("tree", [])
            if item["type"] == "blob" and any(item["path"].endswith(ext) for ext in indexable_extensions)
        ]
        
        stats = {
            "files_found": len(files_to_index),
            "files_indexed": 0,
            "chunks_created": 0,
            "errors": []
        }
        
        repo_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"github:{repo_full_name}")
        pool = await get_pool()
        
        for file_info in files_to_index:
            try:
                content_response = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/contents/{file_info['path']}?ref={branch}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github.raw+json",
                    }
                )
                
                if content_response.status_code != 200:
                    stats["errors"].append(f"{file_info['path']}: Failed to fetch")
                    continue
                
                content = content_response.text
                file_path_hash = hashlib.sha256(file_info['path'].encode()).hexdigest()
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO file_path_lookup (repo_id, file_path_hash, file_path, file_content_hash)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (repo_id, file_path_hash) DO UPDATE SET
                            file_content_hash = EXCLUDED.file_content_hash,
                            updated_at = NOW()
                        """,
                        repo_uuid,
                        file_path_hash,
                        file_info['path'],
                        content_hash,
                    )
                
                lines = content.splitlines()
                chunk_size = 50
                chunk_index = 0
                
                for start in range(0, len(lines), chunk_size):
                    end = min(start + chunk_size, len(lines))
                    chunk_content = "\n".join(lines[start:end])
                    chunk_hash = hashlib.sha256(chunk_content.encode()).hexdigest()
                    
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO code_chunks (repo_id, file_path_hash, chunk_hash, chunk_index, start_line, end_line)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            ON CONFLICT (repo_id, file_path_hash, chunk_index) DO UPDATE SET
                                chunk_hash = EXCLUDED.chunk_hash,
                                start_line = EXCLUDED.start_line,
                                end_line = EXCLUDED.end_line,
                                updated_at = NOW()
                            """,
                            repo_uuid,
                            file_path_hash,
                            chunk_hash,
                            chunk_index,
                            start + 1,
                            end,
                        )
                    
                    chunk_index += 1
                    stats["chunks_created"] += 1
                
                stats["files_indexed"] += 1
                
            except Exception as e:
                stats["errors"].append(f"{file_info['path']}: {str(e)}")
        
        return {
            "status": "success",
            "repo": repo_full_name,
            "branch": branch,
            "stats": stats
        }


@router.get("/stats/{workspace_id}")
async def api_get_indexing_stats(workspace_id: str):
    """Get indexing statistics for a workspace."""
    pool = await get_pool()
    
    async with pool.acquire() as conn:
        files_count = await conn.fetchval(
            "SELECT COUNT(*) FROM file_path_lookup WHERE repo_id = $1::uuid",
            uuid.UUID(workspace_id),
        )
        chunks_count = await conn.fetchval(
            "SELECT COUNT(*) FROM code_chunks WHERE repo_id = $1::uuid",
            uuid.UUID(workspace_id),
        )
    
    return {
        "workspace_id": workspace_id,
        "files_indexed": files_count or 0,
        "chunks_created": chunks_count or 0,
    }


@router.get("/files/{workspace_id}")
async def api_list_indexed_files(workspace_id: str):
    """List all indexed files for a given workspace."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        files = await conn.fetch(
            """
            SELECT fpl.file_path, fpl.repo_id, COUNT(cc.id) as chunk_count
            FROM file_path_lookup fpl
            LEFT JOIN code_chunks cc ON fpl.repo_id = cc.repo_id AND fpl.file_path_hash = cc.file_path_hash
            WHERE fpl.repo_id = $1::uuid
            GROUP BY fpl.file_path, fpl.repo_id
            ORDER BY fpl.file_path
            """,
            uuid.UUID(workspace_id),
        )
        return {
            "files": [
                {"file_path": r["file_path"], "repo_id": str(r["repo_id"]), "chunk_count": r["chunk_count"]}
                for r in files
            ]
        }


@router.get("/chunks/{workspace_id}")
async def api_list_file_chunks(workspace_id: str, file_path: str, repo_id: str):
    """List chunks for a specific file."""
    pool = await get_pool()
    file_path_hash = hashlib.sha256(file_path.encode()).hexdigest()
    
    async with pool.acquire() as conn:
        chunks = await conn.fetch(
            """
            SELECT chunk_index, start_line, end_line, chunk_hash
            FROM code_chunks
            WHERE repo_id = $1::uuid AND file_path_hash = $2
            ORDER BY chunk_index
            """,
            uuid.UUID(repo_id),
            file_path_hash,
        )
        return {
            "file_path": file_path,
            "chunks": [dict(c) for c in chunks]
        }


@router.get("/chunk-content/{workspace_id}")
async def api_get_chunk_content(
    workspace_id: str,
    repo_full_name: str,
    file_path: str,
    start_line: int,
    end_line: int
):
    """Fetch the actual code content for a specific chunk from GitHub."""
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.raw+json",
            }
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch file")
        
        content = response.text
        lines = content.splitlines()
        chunk_content = "\n".join(lines[start_line - 1:end_line])
        
        return {
            "repo_full_name": repo_full_name,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "content": chunk_content,
        }
