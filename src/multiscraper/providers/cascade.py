"""Cascade logic: try providers in priority order, pick best match.

The cascade has two phases:
1. Identification: search by name, pick best candidate above threshold.
2. Media: for each wanted media type, try providers in priority order.

If a provider raises ``ProviderBlockedError`` (e.g. ScreenScraper
returns 429/430/503 or a Cloudflare challenge), the cascade marks
the provider as blocked in ``blocked_providers`` and continues with
the next one. If every media provider ends up blocked the cascade
raises ``AllProvidersBlocked`` and the orchestrator aborts the run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from multiscraper.models import (
    Candidate,
    GameMetadata,
    IdentifyMethod,
    MediaFile,
    MediaRef,
    MediaType,
    Rom,
    ScrapedResult,
    ScrapeStatus,
)
from multiscraper.providers.base import AllProvidersBlocked, ProviderBlockedError
from multiscraper.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


class CascadeResult:
    """Internal result from run_cascade, wrapped into ScrapedResult."""

    def __init__(
        self,
        rom: Rom,
        status: ScrapeStatus,
        chosen: Candidate | None = None,
        media: dict[MediaType, MediaRef] | None = None,
        identify_method: IdentifyMethod = IdentifyMethod.NAME_ONLY,
    ) -> None:
        self.rom = rom
        self.status = status
        self.identify_method = identify_method
        self.chosen = chosen
        self.media: dict[MediaType, MediaRef] = media or {}
        self.fetched_at = datetime.now(tz=UTC)
        if chosen is not None:
            self.chosen_provider: str | None = chosen.provider
            self.match_score: float | None = chosen.match_score
            self.metadata: GameMetadata | None = GameMetadata(
                name=chosen.name,
                desc=chosen.description,
                releasedate=chosen.releasedate,
                developer=chosen.developer,
                publisher=chosen.publisher,
                genre=chosen.genre,
                players=chosen.players,
                rating=chosen.rating,
            )
        else:
            self.chosen_provider = None
            self.match_score = None
            self.metadata = None

    def to_scraped_result(
        self, media_files: list[MediaFile] | None = None,
    ) -> ScrapedResult:
        return ScrapedResult(
            rom=self.rom,
            status=self.status,
            identify_method=self.identify_method,
            chosen_provider=self.chosen_provider,
            match_score=self.match_score,
            metadata=self.metadata,
            media=media_files if media_files is not None else [],
            fetched_at=self.fetched_at,
        )


async def run_cascade(
    rom: Rom,
    registry: ProviderRegistry,
    match_threshold: float,
    blocked_providers: set[str],
    wanted_media: set[MediaType],
) -> CascadeResult:
    """Run the provider cascade for a single ROM.

    Args:
        rom: The ROM to scrape.
        registry: Provider registry with all providers.
        match_threshold: Minimum match score to accept.
        blocked_providers: Mutable set of provider names currently
            blocked. Updated in place when a provider raises
            ``ProviderBlockedError``.
        wanted_media: Set of media types to fetch.

    Returns:
        CascadeResult with status OK, PARTIAL, NO_MATCH, or BLOCKED.

    Raises:
        AllProvidersBlocked: if every media provider ends up in
            ``blocked_providers`` during this call.
    """
    all_providers = registry.all_providers
    available = [p for p in all_providers if p.name not in blocked_providers]
    media_providers = [p for p in available if not p.is_identifier_only]

    if not media_providers:
        raise AllProvidersBlocked(list(blocked_providers))

    best_candidate: Candidate | None = None
    for provider in list(media_providers):  # iterate a copy
        if provider.name in blocked_providers:
            continue
        try:
            candidates = await provider.search(rom)
        except ProviderBlockedError as exc:
            logger.warning(
                "provider_blocked provider=%s rom=%s reason=%s",
                provider.name, rom.raw_name, exc.reason,
            )
            blocked_providers.add(provider.name)
            continue
        except Exception as exc:
            logger.warning(
                "cascade_provider_search_failed provider=%s rom=%s err=%s",
                provider.name, rom.raw_name, type(exc).__name__,
            )
            continue
        if not candidates:
            logger.debug(
                "cascade_provider_no_results provider=%s rom=%s",
                provider.name, rom.raw_name,
            )
            continue
        for cand in candidates:
            if best_candidate is None or cand.match_score > best_candidate.match_score:
                best_candidate = cand
        if best_candidate is not None and best_candidate.match_score >= match_threshold:
            break

    # Re-evaluate: if all media providers got blocked mid-run, abort.
    remaining = [p for p in media_providers if p.name not in blocked_providers]
    if not remaining:
        raise AllProvidersBlocked(list(blocked_providers))

    if best_candidate is None or best_candidate.match_score < match_threshold:
        return CascadeResult(rom=rom, status=ScrapeStatus.NO_MATCH)

    media: dict[MediaType, MediaRef] = {}
    for mt in wanted_media:
        for provider in remaining:
            if mt not in provider.supported_media:
                continue
            try:
                refs = await provider.fetch_media(best_candidate, {mt})
            except ProviderBlockedError as exc:
                logger.warning(
                    "provider_blocked_fetch provider=%s type=%s rom=%s reason=%s",
                    provider.name, mt.value, rom.raw_name, exc.reason,
                )
                blocked_providers.add(provider.name)
                continue
            except Exception as exc:
                logger.warning(
                    "cascade_fetch_media_failed provider=%s type=%s rom=%s err=%s",
                    provider.name, mt.value, rom.raw_name, type(exc).__name__,
                )
                continue
            if mt in refs:
                media[mt] = refs[mt]
                break

    status = ScrapeStatus.OK if len(media) > 0 else ScrapeStatus.PARTIAL

    return CascadeResult(
        rom=rom,
        status=status,
        chosen=best_candidate,
        media=media,
    )
