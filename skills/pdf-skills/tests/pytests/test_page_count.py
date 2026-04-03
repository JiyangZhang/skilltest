"""
Test 1: page count extraction.

The agent is asked how many pages guide.pdf has (3 pages).
We check that "3" appears somewhere in the output.
"""
import re
import os


def test_output_mentions_page_count(agent_output):
    # Accept "3", "three", or "3 pages" anywhere in the output (case-insensitive)
    found = re.search(r"\b3\b|three", agent_output, re.IGNORECASE)
    assert found, (
        f"Expected the agent to report 3 pages, but got:\n{agent_output[:300]}"
    )
