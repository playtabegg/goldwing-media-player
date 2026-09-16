"""Checking for a new Player, only when a person asks.

The doctrine, so the code cannot drift from it:

* **Manual.** Nothing here runs unless the Help menu item is clicked. There
  is no timer, no startup check, no background poll.
* **Almost stateless.** Nothing identifying is remembered: no last-checked
  time, no skipped version, no machine id. Each check is the same request
  with the same headers. The one mark on disk is the highest feed version
  a successful signed parse has already shown this machine, so a still-
  validly-signed older feed cannot be offered again (29 Aug 2026).
* **Off-thread, cancelled on close.** The request runs on a worker; closing
  the window drops the answer.
* **Fail closed, in one sentence.** A feed that does not verify, a host that
  is not ours, a hash that does not match: each ends in one sentence to the
  person and nothing on disk. There is no "unsigned but probably fine".
* **Never gates play.** The update code is imported only from the Help
  menu handler. A disc plays whether or not this package works.

What it trusts: the minisign public keys in :mod:`keys` (compiled in), and
nothing else. The feed is ``wti.appcast/1`` (``UPDATER-APPS-PORT-PLAN
_2026-08-28.md`` §4.2), signed with a key that never leaves the publisher's
machine. A new key is delivered by a build signed with the old one.
"""
