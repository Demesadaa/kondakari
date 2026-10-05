"""Console entry point for the Streamlit client."""

import sys
from pathlib import Path

from streamlit.web import cli as streamlit_cli


def main() -> int:
    app_path = Path(__file__).with_name("web.py")
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--theme.base=light",
        "--theme.primaryColor=#809f43",
        "--theme.backgroundColor=#f7f3e8",
        "--theme.secondaryBackgroundColor=#fffdf7",
        "--theme.textColor=#262724",
    ]
    return streamlit_cli.main()
