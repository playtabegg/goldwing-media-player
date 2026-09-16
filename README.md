# Goldwing Media Player

**A free media player for movies, music and compatible game discs.**

Goldwing brings playback, chapters and your disc's artwork into one Windows
app. It uses **VLC's libVLC playback engine** and is free software under the
**GNU General Public License, version 3 or later**.

Play movies, albums and compatible Windows game discs made and distributed
through [We The Indies](https://wetheindies.com), an independent physical
publisher for games, films and music. That includes compatible discs built
with [Rialto 1.5](https://wetheindies.com/resources/rialto), the free disc-making
software for independent developers, filmmakers and musicians. Goldwing also
plays supported unprotected discs you already own.

## Download for Windows

[**Download Goldwing Media Player 1.0.0**](https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.0/GoldwingMediaPlayer-Setup-1.0.0.exe)

Windows 10 (1809 or later) or Windows 11, 64-bit. **The installer includes the
Player and its playback libraries. You do not need to install VLC, Python or
other prerequisites, or run terminal commands.**

Run the installer. At the end, leave **Open Goldwing Media Player** selected
to open it, or use its Start menu shortcut later. Choose **Open a folder**,
**Open a disc image**, or a disc in your drive. Install for your Windows user;
the installer does not take over file associations.

The installer is code-signed by **We The Indies, LLC**. Check the publisher and
the [published SHA-256](https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.0/GoldwingMediaPlayer-Setup-1.0.0.exe.sha256)
before installing. A new signed installer can still prompt Windows SmartScreen.

**Mac and Linux versions are coming soon.** Today's installer is for Windows.

## What it plays

- **Movies:** unprotected DVD-Video and Blu-ray, with chapters and supported
  menus. Blu-ray HDMV menus are supported; Java-based BD-J menus are not.
- **Music:** audio CDs, with CD-TEXT track names when supplied by the disc,
  and supported music content on movie/data discs.
- **We The Indies and Rialto discs:** supported movies, music and Windows
  game launchers, with the title, chapters and actual case/disc artwork
  supplied on the disc.
- **Game discs:** open a compatible Windows launcher/menu to install or
  start the game. The game keeps its own system requirements; Goldwing is
  not a console emulator.
- **Images, folders and archives:** open supported ISO images, BDMV and
  VIDEO_TS folders, or browse files on data and M-Disc archives.

A readable disc and matching optical drive are needed for physical media;
folders and images play without a drive. Compatibility depends on the disc's
format and content.

## Your copies and updates

Keep a disc folder on your shelf to open the same copy again. Playback needs
no account, and Goldwing has no telemetry or automatic update nag.

Use **Help > Check for a new Goldwing** when you want to check for updates.
Goldwing verifies the signed feed, installer signature and checksum before
offering an update. It asks before downloading or installing.

## Protected commercial discs and the roadmap

**CSS-protected DVDs and AACS-protected Blu-rays do not play in 1.0.0.**
Goldwing does not include a descrambler or claim licensed protected playback.
Code-signing the installer does not grant disc-content licences.

Officially licensed protected-disc playback is planned for a future update.
We will obtain the appropriate licences and meet their requirements before
offering it. See [DVD CCA](https://www.dvdcca.org/) and
[AACS licensing](https://aacsla.com/license-aacs/) for those processes.

**Ultimately, the hurdle for me is affording the licences that let me offer
official protected-disc playback.**

## Source and contributors

Goldwing is free software under the **GNU General Public License, version 3
or later**. See [LICENSE](LICENSE). VLC's playback libraries and other bundled
components retain their own licences, listed in the installed notices.

[Building from source](BUILDING.md) is for contributors; installer users do
not need those steps. Maintainers can use the [release guide](RELEASING.md).
The version's release tag identifies its corresponding source. Signing keys,
vendored runtime binaries and private disc libraries are excluded from Git.
