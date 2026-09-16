"""A portable release bundle must be accepted by the actual Player verifier."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import release_feed
import wti_minisign

from wti_player.update.feed import parse_feed
from wti_player.update.minisig import PublicKey, verify_bytes


def materials(tmp_path):
    seed, key_id = bytes(range(32)), b'testonly'
    key = tmp_path / 'test.key'
    key.write_bytes(key_id + seed)
    pub = PublicKey(key_id, wti_minisign.wti_ed25519.public_key(seed))
    installer = tmp_path / 'GoldwingMediaPlayer-Setup-1.0.1.exe'
    installer.write_bytes(b'ephemeral test artifact only')
    return key, pub, installer


def test_signed_bundle_roundtrips_through_player_and_detects_tampering(tmp_path, monkeypatch):
    key, pub, installer = materials(tmp_path)
    monkeypatch.setattr(release_feed, 'trusted_keys', lambda: [pub])
    monkeypatch.setattr(release_feed, 'authenticode_subject', lambda _: 'We The Indies, LLC')
    result = release_feed.publish(app='goldwing', channel='stable', version='1.0.1', artifact=installer,
        url=f'https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.1/{installer.name}',
        key_path=key, out_dir=tmp_path / 'release')
    raw = result['feed'].read_bytes()
    assert verify_bytes(raw, result['feed_sig'].read_text(), pub)
    release = parse_feed(raw, result['feed_sig'].read_text(), [pub])
    assert release.version == '1.0.1'
    assert verify_bytes(result['artifact'].read_bytes(), release.signature, pub)
    assert result['hash'].read_text().startswith(release.sha256 + '  ')
    result['artifact'].write_bytes(b'tampered')
    assert release_feed.check_folder(tmp_path / 'release', wti_minisign.PublicKey(pub.key_id, pub.raw))


def test_untrusted_release_key_is_refused_before_staging(tmp_path, monkeypatch):
    key, _, installer = materials(tmp_path)
    monkeypatch.setattr(release_feed, 'authenticode_subject', lambda _: 'We The Indies, LLC')
    out = tmp_path / 'release'
    with pytest.raises(release_feed.PublishError, match='not trusted'):
        release_feed.publish(app='goldwing', channel='stable', version='1.0.1', artifact=installer,
            url=f'https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.1/{installer.name}',
            key_path=key, out_dir=out)
    assert not out.exists()
