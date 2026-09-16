from pathlib import Path


def test_initial_public_workflows_cannot_sign_or_release_on_a_tag():
    root = Path(__file__).resolve().parents[2] / '.github/workflows'
    assert 'if: ${{ false }}' in (root / 'build-on-tag.yml').read_text()
    assert "if: ${{ false && github.event.workflow_run.conclusion == 'success' }}" in (root / 'release-on-tag.yml').read_text()


def test_missing_feed_does_not_claim_an_installation_is_up_to_date():
    from wti_player.update.feed import NOTHING_PUBLISHED
    assert 'newest' not in NOTHING_PUBLISHED.lower()
    assert 'unchanged' in NOTHING_PUBLISHED.lower()
