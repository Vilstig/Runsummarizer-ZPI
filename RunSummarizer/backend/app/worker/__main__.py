"""The import worker: ``python -m app.worker [--provider NAME]``.

It runs one import loop per configured provider, or only ``--provider``'s, and a token
maintenance loop for those providers, until SIGTERM or SIGINT, then finishes the items
being imported and exits.
"""

import argparse
import logging
import signal
import sys
from collections.abc import Sequence

import anyio

from app.config.settings import POSTGRES_DSN, TOKEN_ENCRYPTION_KEY
from app.core.logging import configure_logging
from app.db.client import dispose_engine
from app.domain.enums import Provider
from app.providers.base import ProviderDefinition
from app.providers.registry import PROVIDERS
from app.worker.loop import ImportWorker
from app.worker.token_maintenance import TokenMaintenance

logger = logging.getLogger("app.worker")


class ProviderNotConfiguredError(Exception):
    """The provider asked for with ``--provider`` lacks its settings."""


def select_providers(
    only: Provider | None = None,
) -> tuple[list[ProviderDefinition], dict[Provider, str]]:
    """The registered providers to run, and why each of the others is left out
    (``'not configured'`` | ``'not selected'``).

    Without ``only``, every configured provider runs. With it, only ``only`` runs, and
    ``ProviderNotConfiguredError`` is raised when it isn't configured.
    """
    if only is not None and not PROVIDERS[only].is_configured():
        raise ProviderNotConfiguredError(only)
    running: list[ProviderDefinition] = []
    skipped: dict[Provider, str] = {}
    for provider, definition in PROVIDERS.items():
        if only is not None and provider != only:
            skipped[provider] = "not selected"
        elif only is None and not definition.is_configured():
            skipped[provider] = "not configured"
        else:
            running.append(definition)
    return running, skipped


async def _stop_on_signal(stop: anyio.Event) -> None:
    """Set ``stop`` on the first SIGTERM or SIGINT."""
    with anyio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signals:
        async for signum in signals:
            logger.info("%s received; stopping after the current items", signum.name)
            stop.set()
            return


async def run_worker(definitions: Sequence[ProviderDefinition]) -> None:
    """Run an ``ImportWorker`` for each of ``definitions``, all stopped by one event, and
    a ``TokenMaintenance`` for them in a task of its own. Maintenance still running once
    the import loops stopped is cancelled."""
    stop = anyio.Event()
    workers = [
        ImportWorker(
            definition.importer(),
            budget_policy=definition.budget_policy,
            token_refresher=definition.token_refresher,
        )
        for definition in definitions
    ]
    maintenance = TokenMaintenance(definitions)
    try:
        async with anyio.create_task_group() as tasks:
            # Windows has no signal handlers in the event loop: Ctrl+C cancels the
            # workers instead, and their items' leases expire.
            if sys.platform != "win32":
                tasks.start_soon(_stop_on_signal, stop)
            if maintenance.providers:
                tasks.start_soon(maintenance.run, stop)
            async with anyio.create_task_group() as loops:
                for worker in workers:
                    loops.start_soon(worker.run, stop)
            tasks.cancel_scope.cancel()
    finally:
        await dispose_engine()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument(
        "--provider",
        type=Provider,
        choices=list(PROVIDERS),
        help="run only this provider's import loop",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    required = {"POSTGRES_DSN": POSTGRES_DSN, "TOKEN_ENCRYPTION_KEY": TOKEN_ENCRYPTION_KEY}
    missing = [name for name, value in required.items() if not value]
    if missing:
        logger.error("import worker: missing settings: %s", ", ".join(missing))
        return 1
    try:
        running, skipped = select_providers(args.provider)
    except ProviderNotConfiguredError:
        logger.error("import worker: %s is not configured", args.provider)
        return 1
    if not running:
        logger.error("import worker: no provider is configured")
        return 1
    if skipped:
        logger.info(
            "import worker: skipping %s",
            ", ".join(f"{provider.value} ({reason})" for provider, reason in skipped.items()),
        )

    logger.info(
        "import worker started for %s",
        ", ".join(definition.provider.value for definition in running),
    )
    try:
        anyio.run(run_worker, running)
    except KeyboardInterrupt:
        logger.info("import worker interrupted")
        return 130
    logger.info("import worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
