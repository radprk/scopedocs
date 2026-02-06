"""Async job worker for background processing."""

import asyncio
import logging
import signal
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass

from backend.storage.postgres import (
    get_pool, claim_pending_job, complete_job, fail_job
)

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """Result of a job execution."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# Job handlers registry
_handlers: Dict[str, Callable] = {}


def register_handler(job_type: str):
    """Decorator to register a job handler."""
    def decorator(func: Callable):
        _handlers[job_type] = func
        return func
    return decorator


def get_handler(job_type: str) -> Optional[Callable]:
    """Get handler for a job type."""
    return _handlers.get(job_type)


class JobWorker:
    """Worker that processes jobs from the queue."""
    
    def __init__(
        self,
        job_types: list = None,
        poll_interval: float = 1.0,
        max_concurrent: int = 5,
    ):
        self.job_types = job_types
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self._running = False
        self._tasks: set = set()
    
    async def start(self):
        """Start the worker."""
        self._running = True
        logger.info(f"Job worker started (types: {self.job_types or 'all'})")
        
        while self._running:
            # Clean up completed tasks
            done = {t for t in self._tasks if t.done()}
            self._tasks -= done
            
            # Check if we can take more jobs
            if len(self._tasks) >= self.max_concurrent:
                await asyncio.sleep(self.poll_interval)
                continue
            
            # Try to claim a job
            try:
                job = await claim_pending_job(self.job_types)
                if job:
                    task = asyncio.create_task(self._process_job(job))
                    self._tasks.add(task)
                else:
                    await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Error claiming job: {e}")
                await asyncio.sleep(self.poll_interval)
    
    async def stop(self):
        """Stop the worker gracefully."""
        self._running = False
        if self._tasks:
            logger.info(f"Waiting for {len(self._tasks)} tasks to complete...")
            await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("Job worker stopped")
    
    async def _process_job(self, job: Dict[str, Any]):
        """Process a single job."""
        job_id = job["id"]
        job_type = job["job_type"]
        payload = job["payload"]
        
        logger.info(f"Processing job {job_id} ({job_type})")
        
        handler = get_handler(job_type)
        if not handler:
            await fail_job(job_id, f"No handler for job type: {job_type}")
            logger.error(f"No handler for job type: {job_type}")
            return
        
        try:
            result = await handler(payload)
            
            if isinstance(result, JobResult):
                if result.success:
                    await complete_job(job_id, result.data)
                    logger.info(f"Job {job_id} completed successfully")
                else:
                    await fail_job(job_id, result.error or "Unknown error")
                    logger.error(f"Job {job_id} failed: {result.error}")
            else:
                # Assume success if handler returns dict or None
                await complete_job(job_id, result if isinstance(result, dict) else None)
                logger.info(f"Job {job_id} completed")
                
        except Exception as e:
            await fail_job(job_id, str(e))
            logger.exception(f"Job {job_id} failed with exception")


async def run_worker(job_types: list = None):
    """Run the job worker (main entry point)."""
    worker = JobWorker(job_types=job_types)
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
    
    try:
        await worker.start()
    except asyncio.CancelledError:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(run_worker())
