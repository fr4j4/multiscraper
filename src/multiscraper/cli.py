"""CLI entry point for multiscraper."""

import click

from multiscraper import __version__


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """multiscraper: parallel multi-source scraper for retro gaming frontends."""


if __name__ == "__main__":
    main()
