# Releasing Goldwing Media Player

The public repository includes the Player, build tools and signed-feed
publisher. Installer signing and feed signing are separate steps. Neither
build nor feed preparation pushes code or publishes a release.

## A routine update

1. Bump `VERSION` in `wti_player/version.py` to the next `X.Y.Z`, update
   the README and GitHub release description, commit reviewed changes to `master`, and check the tree is
   clean. Keep the product name **Goldwing Media Player**.
2. Run the unit suite and lint. Prepare the pinned VLC runtime, build the EXE
   and installer, and check the generated licence notice:

   ```powershell
   python -m pytest tests/unit -q
   python -m ruff check .
   python tools/fetch_vlc.py
   python tools/build_exe.py --clean
   python tools/build_installer.py
   python tools/licence_notice.py --check
   ```

3. Use an authorized Azure signing session and `python tools/publish.py --yes`.
   Require Authenticode **Valid**, publisher **We The Indies, LLC**, and the
   generated `.sha256` sidecar. Check actual playback from the built/installed
   Player; a design mockup is not playback proof.
4. With separate authority to use the existing protected app-release key,
   generate and verify the update bundle. Substitute the new version and
   actual key path; never place keys in the checkout:

   ```powershell
   python tools/release_feed.py publish --app goldwing --channel stable --version X.Y.Z --artifact dist/GoldwingMediaPlayer-Setup-X.Y.Z.exe --key <protected-key-path> --out dist/release --url https://github.com/playtabegg/goldwing-media-player/releases/download/vX.Y.Z/GoldwingMediaPlayer-Setup-X.Y.Z.exe
   ```

   The publisher requires the existing trusted release key and the signed
   installer. It derives the hash after signing, embeds the installer's
   minisign signature in `latest.json`, signs the feed and verifies disk files
   before reporting success. `--no-authenticode` is strictly for synthetic
   tests; never use it for a real release.
5. With publication authority, push the reviewed source and exact release tag
   to the safe public repository. Draft the release with exactly four assets:

   - `GoldwingMediaPlayer-Setup-X.Y.Z.exe`
   - `GoldwingMediaPlayer-Setup-X.Y.Z.exe.sha256`
   - `latest.json`
   - `latest.json.minisig`

   The standalone installer `.sig` is local verification material; its text
   is already embedded in the feed. Publish only after the complete draft is
   verified. Keep the latest release stable so the existing feed address
   continues to work.
6. Signed out, download all four files, verify the feed with the Player's
   trusted public keys, verify installer/hash/signatures, then test
   **Help > Check for a new Goldwing** in the installed previous version.
   Verify the offered version, prompted install and restart. Never replace
   an existing release's installer bytes under the same version URL.

The installer URL, version and lowercase post-signing hash must change
together anywhere the website exposes download metadata. Installed Players
read the latest signed feed, so their update channel does not need a website
redeploy for every release.

## Fresh repository and automation

The initial public repository must be a fresh source snapshot. Do not make
private development history public. Preserve the old repository as a private
archive, including its old pull-request references and Actions history.

**Build on Tag and Release on Tag are disabled in this launch snapshot.**
Keep them disabled in GitHub too until the fresh repository has its matching
Azure federated identity, protected `release` environment/reviewer, tag rules
and branch protection. Once those are independently verified, reviewed
workflow changes can enable routine signed builds. A successful workflow
creates a draft; publication remains a deliberate release action.

Changing repository visibility or publishing the first release requires
specific publication authority. Signing an installer is not publication.
