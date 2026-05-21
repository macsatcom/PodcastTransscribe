import asyncio
import logging
import os
import sys
import signal
from uuid import UUID

logger = logging.getLogger(__name__)


class PortalManager:
    def __init__(self):
        self._processes: dict[UUID, asyncio.subprocess.Process] = {}

    def is_running(self, portal_id: UUID) -> bool:
        proc = self._processes.get(portal_id)
        return proc is not None and proc.returncode is None

    async def start(self, portal):
        if self.is_running(portal.id):
            logger.info("Portal %s already running", portal.id)
            return

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn",
            "--factory", "app.portal_server:create_app",
            "--host", "0.0.0.0",
            "--port", str(portal.port),
            env={
                **os.environ,
                "PORTAL_ID": str(portal.id),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[portal.id] = proc
        logger.info("Started portal %s on port %s", portal.id, portal.port)

        asyncio.create_task(self._consume_output(proc))
        asyncio.create_task(self._watch(portal.id, proc))

    async def _consume_output(self, proc):
        async for line in proc.stdout:
            logger.info("Portal output: %s", line.decode().rstrip())
        async for line in proc.stderr:
            logger.warning("Portal stderr: %s", line.decode().rstrip())

    async def _watch(self, portal_id, proc):
        await proc.wait()
        logger.warning("Portal %s exited with code %s", portal_id, proc.returncode)
        self._processes.pop(portal_id, None)

    async def stop(self, portal_id: UUID):
        proc = self._processes.pop(portal_id, None)
        if proc is None:
            return
        try:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass
        logger.info("Stopped portal %s", portal_id)

    async def start_all(self, portals):
        for portal in portals:
            if portal.enabled:
                await self.start(portal)

    async def stop_all(self):
        for pid in list(self._processes.keys()):
            await self.stop(pid)


portal_manager = PortalManager()
