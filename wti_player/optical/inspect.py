"""Read a BDMV folder and say what is in it, in words.

This is the reporting half of menu preview mode — the part that makes the
Player a tool for us and not only a player for them. It walks the disc's own
files with our parsers and produces a plain report: what plays first, what the
Top Menu points at, which playlists carry an interactive-graphics stream and
which do not, what each clip actually contains.

When a menu that should come up does not, this is what says why: no IG stream
in the STN table, or a Top Menu slot pointing at a movie object that is not
there, or BD-J where HDMV was expected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..formats import clpi, index_bdmv, mpls


@dataclass(frozen=True)
class Line:
    """One row of the report."""

    text: str
    detail: str = ""
    #: "ok", "note", or "problem" — what colour it should read as.
    tone: str = "ok"
    children: tuple[Line, ...] = ()


@dataclass
class Report:
    root: Path
    lines: list[Line] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.problems

    def as_text(self) -> str:
        out: list[str] = [str(self.root), ""]

        def render(line: Line, depth: int) -> None:
            prefix = "  " * depth
            out.append(f"{prefix}{line.text}" + (f"  ·  {line.detail}" if line.detail else ""))
            for child in line.children:
                render(child, depth + 1)

        for line in self.lines:
            render(line, 0)
        return "\n".join(out)


def _describe_entry(name: str, entry: index_bdmv.IndexEntry) -> Line:
    if not entry.is_present:
        return Line(name, "not set", tone="note")
    if entry.is_bdj:
        return Line(name, f"BD-J object {entry.bdjo_name!r}, needs Java", tone="problem")
    return Line(name, f"HDMV movie object {entry.id_ref}", tone="ok")


def inspect_bdmv(root: Path) -> Report:
    """Everything the disc's files say, whether or not it will play."""
    bdmv = root / "BDMV" if (root / "BDMV").is_dir() else root
    report = Report(root=root)

    try:
        index = index_bdmv.read_index(bdmv)
    except index_bdmv.IndexError_ as exc:
        report.problems.append(str(exc))
        report.lines.append(Line("index.bdmv", str(exc), tone="problem"))
        return report

    objects = index_bdmv.read_movie_objects(bdmv)
    report.lines.append(
        Line(
            "index.bdmv",
            f"version {index.version} · {index.title_count} titles",
            children=(
                _describe_entry("First Play", index.first_play),
                _describe_entry("Top Menu", index.top_menu),
                *(
                    _describe_entry(f"Title {number + 1}", entry)
                    for number, entry in enumerate(index.titles)
                ),
            ),
        )
    )
    if index.uses_bdj:
        report.problems.append("This disc uses BD-J, which GoldWing does not run.")
    if not index.has_top_menu:
        report.lines.append(
            Line("Top Menu", "this disc has no Top Menu slot", tone="note")
        )

    if objects:
        report.lines.append(
            Line(
                "MovieObject.bdmv",
                f"{len(objects)} movie objects",
                children=tuple(
                    Line(
                        f"Object {number}",
                        f"{obj.command_count} navigation "
                        f"command{'' if obj.command_count == 1 else 's'}",
                    )
                    for number, obj in enumerate(objects)
                ),
            )
        )
        highest = max(
            (entry.id_ref for entry in (index.first_play, index.top_menu, *index.titles)
             if entry.is_present and not entry.is_bdj),
            default=-1,
        )
        if highest >= len(objects):
            report.problems.append(
                f"The index points at movie object {highest}, but the disc only has "
                f"{len(objects)}."
            )

    playlists = mpls.read_all(bdmv / "PLAYLIST")
    clips = clpi.read_all(bdmv / "CLIPINF")
    if not playlists:
        report.problems.append("There are no readable playlists on this disc.")

    menu_playlists = 0
    playlist_lines: list[Line] = []
    for playlist in playlists:
        streams: list[Line] = []
        for item in playlist.play_items:
            for stream in item.streams:
                streams.append(
                    Line(
                        f"PID 0x{stream.pid:04x}",
                        f"{stream.kind} · {stream.coding_name}"
                        + (f" · {stream.language}" if stream.language else ""),
                        tone="note" if stream.kind == "interactive" else "ok",
                    )
                )
        is_menu = playlist.has_interactive_graphics
        menu_playlists += int(is_menu)
        marks = len(playlist.chapters_ms)
        detail = (
            f"{playlist.duration_ms / 1000:.1f}s · {marks} chapter"
            + ("" if marks == 1 else "s")
        )
        if is_menu:
            detail += " · interactive graphics"
        elif any(item.is_still for item in playlist.play_items):
            detail += " · still"
        playlist_lines.append(
            Line(
                f"{playlist.name}.mpls",
                detail,
                tone="note" if is_menu else "ok",
                children=tuple(streams),
            )
        )
        for clip_id in playlist.clip_ids:
            if clip_id not in clips:
                report.problems.append(
                    f"{playlist.name}.mpls points at clip {clip_id}, which is not on the disc."
                )
    report.lines.append(Line("PLAYLIST", f"{len(playlists)} playlists", children=tuple(playlist_lines)))

    clip_lines: list[Line] = []
    for clip_id, info in clips.items():
        clip_lines.append(
            Line(
                f"{clip_id}.clpi",
                f"{info.duration_ms / 1000:.1f}s · {info.source_packet_count} packets · "
                + ", ".join(f"{stream.kind} 0x{stream.pid:04x}" for stream in info.streams),
                tone="note" if info.has_interactive_graphics else "ok",
            )
        )
        stream_file = bdmv / "STREAM" / f"{clip_id}.m2ts"
        if not stream_file.is_file():
            report.problems.append(f"{clip_id}.clpi has no matching {clip_id}.m2ts.")
    report.lines.append(Line("CLIPINF", f"{len(clips)} clips", children=tuple(clip_lines)))

    if index.has_top_menu and menu_playlists == 0:
        report.problems.append(
            "This disc has a Top Menu, but no playlist carries an interactive-graphics "
            "stream, so there are no buttons for the menu to show."
        )

    for problem in report.problems:
        report.lines.append(Line("Problem", problem, tone="problem"))
    return report
