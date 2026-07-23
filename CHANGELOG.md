# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-23

### Added
- Parallel multi-source scraper with asyncio + aiohttp.
- 13 data source providers (ScreenScraper, IGDB, RAWG, MobyGames, GiantBomb,
  RetroAchievements, TheGamesDB, LibRetro Thumbnails, OpenVGDB, GameFAQs,
  Hasheous, local_override, local_fallback).
- SSH transport via asyncssh for remote ROM reading.
- SQLite cache with WAL mode and migration system.
- CSV streaming output with one row per ROM.
- EmulationStation gamelist.xml generator.
- Cascading fallback with match threshold and language preference.
- Cloudflare/captcha detection with provider cooldown.
- Graceful shutdown with SIGTERM/SIGINT handling and checkpoint/resume.
- LLM TextGenerator hook (NoOp default, OpenAICompat inactive for v2).
- Full CLI: scrape, validate-config, convert-to-es, list-systems, db, override, doctor.
- Comprehensive documentation (architecture, configuration, CLI, providers, SSH, ES files, logging, research).
