#!/usr/bin/env python3
import argparse
import logging
import sys
import os

# Add project root to path to ensure imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raspberry_pi.core.system import SystemOrchestrator
from raspberry_pi.config.models import SystemMode


def main():
    parser = argparse.ArgumentParser(description="Smart Irrigation System Controller")

    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in SystemMode],
        help="System operation mode (overrides config)",
    )

    # Default config path relative to this script
    default_config = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config", "system_config.yaml"
    )

    parser.add_argument(
        "--config", type=str, default=default_config, help="Path to configuration file"
    )

    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose logging (DEBUG level)"
    )

    args = parser.parse_args()

    # Setup basic logging before Orchestrator takes over
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger = logging.getLogger("main")
    logger.info(f"Starting Smart Irrigation System (Config: {args.config})")

    try:
        orchestrator = SystemOrchestrator(
            config_path=args.config, override_mode=args.mode
        )
        orchestrator.start()

    except KeyboardInterrupt:
        logger.info("Exiting...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
