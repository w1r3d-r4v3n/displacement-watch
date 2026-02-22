def test_markdown_footnotes_shape():
    sample = '''# Displacement Watch Brief — 2026-02-20
## Executive Summary
- Example headline<sup>1</sup>
## Top Developments
1. **Example**<sup>1</sup>
## Footnotes
1. Reuters, “Example,” February 20, 2026, https://example.com (accessed February 20, 2026).
## Appendix A: Quality & Methods Notes
## Appendix B: Trend Signals
'''
    assert "## Footnotes" in sample
    assert "<sup>1</sup>" in sample
    assert "https://" in sample
