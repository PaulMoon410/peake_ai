"""Orchestrate Harold's bounded reading, MCF3 storage, and reflections."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from harold.curator import Curator
from harold.discovery import Candidate, Discovery
from harold.journal import (
    KIND_PAGE,
    KIND_REFLECTION,
    KIND_SESSION,
    KIND_TOPIC,
    Journal,
    JournalEntry,
)
from harold.net import FetchError, PoliteFetcher
from harold.readability import html_to_text, is_probably_article
from harold.reflection import NoteView, Reflection, build_reflection
from harold.sources import WebSearchSource
from harold.topics import (
    OBSERVATION_ROOT,
    TOPIC_SEEDS,
    UNDERSTANDING_ROOT,
    CurriculumTopic,
    find_topic,
    next_topics,
)
from harold.urlguard import UrlRejected
from harold.wiki import WikipediaSource


@dataclass(frozen=True, slots=True)
class HaroldConfig:
    """Budgets and local journal location for a Harold reading session."""

    pages_per_session: int = 8
    pages_per_host: int = 2
    candidates_per_topic: int = 3
    links_per_page: int = 1
    use_model: bool = True
    journal_path: Path = Path(__file__).resolve().parent / "journal.jsonl"

    def __post_init__(self) -> None:
        if self.pages_per_session < 1 or self.pages_per_host < 1:
            raise ValueError("Page budgets must be positive.")
        if self.candidates_per_topic < 1 or self.links_per_page < 0:
            raise ValueError("Candidate limits must be positive and link limits cannot be negative.")


@dataclass
class _Budget:
    """Session page budget with an independent per-host cap."""

    pages_left: int
    pages_per_host: int
    _host_counts: Counter[str] = field(default_factory=Counter)

    def take(self, host: str) -> bool:
        key = host.casefold().rstrip(".")
        if self.pages_left <= 0 or self._host_counts[key] >= self.pages_per_host:
            return False
        self.pages_left -= 1
        self._host_counts[key] += 1
        return True


@dataclass(frozen=True, slots=True)
class PageReport:
    """Outcome of reading and curating one candidate page."""

    url: str
    title: str
    origin: str
    notes_added: int = 0
    notes_uploaded: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class TopicReport:
    """Pages and memory changes made while studying one topic."""

    topic: str
    domain: str
    pages: tuple[PageReport, ...] = ()
    refused: tuple[str, ...] = ()

    @property
    def notes_added(self) -> int:
        return sum(page.notes_added for page in self.pages)

    @property
    def notes_uploaded(self) -> int:
        return sum(page.notes_uploaded for page in self.pages)


class HaroldAgent:
    """Learn from public pages, save observations, and reflect on stored notes."""

    def __init__(
        self,
        store: Any,
        model: Any = None,
        config: HaroldConfig | None = None,
        fetcher: PoliteFetcher | None = None,
        discovery: Discovery | None = None,
        curator: Curator | None = None,
        journal: Journal | None = None,
    ) -> None:
        self.store = store
        self.model = model
        self.config = config or HaroldConfig()
        self.fetcher = fetcher or PoliteFetcher()
        self.web = WebSearchSource(self.fetcher)
        self.wikipedia = WikipediaSource(self.fetcher, search=self.web)
        self.discovery = discovery or Discovery(self.fetcher, self.wikipedia, self.web)
        self.curator = curator or Curator(model=model if callable(model) else None,
                                          use_model=self.config.use_model)
        self.journal = journal or Journal(self.config.journal_path)

    def learn(self, topic_limit: int = 4) -> list[TopicReport]:
        """Study the next uncovered curriculum topics within one session budget."""
        topics = next_topics(self.covered_topics(), limit=max(0, topic_limit))
        budget = _Budget(self.config.pages_per_session, self.config.pages_per_host)
        self.journal.append(JournalEntry.create(KIND_SESSION, detail=f"starting {len(topics)} topic(s)"))
        reports = [self._learn_topic(topic, budget) for topic in topics]
        self.journal.append(JournalEntry.create(
            KIND_SESSION,
            detail=f"finished {len(reports)} topic(s), {sum(r.notes_added for r in reports)} observation(s)",
        ))
        return reports

    def _learn_topic(self, topic: CurriculumTopic, budget: _Budget) -> TopicReport:
        pages: list[PageReport] = []
        refused: list[str] = []
        candidates = self.discovery.for_topic(topic, limit=self.config.candidates_per_topic)
        for candidate in candidates:
            report, _ = self._read(topic, candidate, budget)
            if report is None:
                refused.append(f"{candidate.url} (outside the session budget)")
            else:
                pages.append(report)
        report = TopicReport(topic=topic.name, domain=topic.domain,
                             pages=tuple(pages), refused=tuple(refused))
        self.journal.append(JournalEntry.create(
            KIND_TOPIC, topic=topic.name,
            detail=f"{report.notes_added} observation(s), {len(refused)} page(s) refused",
            notes=report.notes_added, uploaded=report.notes_uploaded,
        ))
        return report

    def _read(
        self, topic: CurriculumTopic, candidate: Candidate, budget: _Budget,
    ) -> tuple[PageReport | None, str]:
        """Fetch one candidate within budget, then curate and store observations."""
        if not budget.take(candidate.host):
            return None, ""
        self.discovery.mark_seen(candidate.url)
        try:
            fetched = self.fetcher.page(candidate.url)
            html = fetched.text
            page = html_to_text(html, url=fetched.url)
            if page.is_empty or not is_probably_article(page.text, topic.keywords):
                detail = "page did not contain enough relevant article text"
                result = PageReport(candidate.url, page.title or candidate.title,
                                    candidate.origin, detail=detail)
            else:
                observations = self.curator.distill(topic, page, fetched.url)
                added = 0
                uploaded = 0
                for observation in observations:
                    record = self.store.add(
                        observation.as_memory_text(), category=topic.category,
                        source=observation.source_url,
                    )
                    if record is None:
                        continue
                    added += 1
                    uploaded += self._upload(record)
                detail = f"{added} new observation(s)"
                result = PageReport(candidate.url, page.title or candidate.title,
                                    candidate.origin, added, uploaded, detail)
        except (FetchError, UrlRejected, OSError, ValueError) as exc:
            html = ""
            result = PageReport(candidate.url, candidate.title, candidate.origin,
                                detail=f"read refused: {exc}")

        self.journal.append(JournalEntry.create(
            KIND_PAGE, topic=topic.name, url=candidate.url, detail=result.detail,
            notes=result.notes_added, uploaded=result.notes_uploaded,
        ))
        return result, html

    def _upload(self, record: dict[str, str]) -> int:
        """Upload one new observation when the configured store supports FTP."""
        if not getattr(self.store, "ftp_configured", False):
            return 0
        try:
            self.store.upload(record)
            return 1
        except Exception as exc:
            self.journal.append(JournalEntry.create(
                KIND_PAGE, detail=f"FTP upload failed: {exc}",
            ))
            return 0

    def _observation_records(self) -> list[dict[str, str]]:
        return [
            record for record in self.store.records
            if str(record.get("c", "")).startswith(OBSERVATION_ROOT + "/")
        ]

    def covered_topics(self) -> set[str]:
        """Curriculum topics with at least one matching observation in memory."""
        records = self._observation_records()
        covered: set[str] = set()
        for topic in TOPIC_SEEDS:
            for record in records:
                if not str(record.get("c", "")).startswith(topic.category):
                    continue
                text = str(record.get("n", "")).casefold()
                if any(keyword.casefold() in text for keyword in topic.keywords):
                    covered.add(topic.name)
                    break
        return covered

    # -- one-off learning ---------------------------------------------------
    def learn_url(self, url: str, topic_name: str = "", domain: str = "External") -> TopicReport:
        """Learn from one specific page the user pointed at."""
        topic = find_topic(topic_name) if topic_name else None
        if topic is None:
            from harold.lexicon import words
            from harold.links import title_from_url

            name = topic_name.strip() or title_from_url(url)
            keywords = tuple(dict.fromkeys(word for word in words(name) if len(word) > 2))[:5]
            topic = CurriculumTopic(domain=domain, name=name, question=name, keywords=keywords)

        budget = _Budget(pages_left=self.config.pages_per_session,
                         pages_per_host=self.config.pages_per_host)
        pages: list[PageReport] = []
        refused: list[str] = []
        for candidate in self.discovery.for_url(url, topic.name):
            report, _ = self._read(topic, candidate, budget)
            if report is None:
                refused.append(f"{candidate.url} (outside the session budget)")
            else:
                pages.append(report)
        report = TopicReport(topic=topic.name, domain=topic.domain,
                             pages=tuple(pages), refused=tuple(refused))
        self.journal.append(JournalEntry.create(
            KIND_TOPIC, topic=topic.name, url=url,
            detail=f"single page, {report.notes_added} observation(s)",
            notes=report.notes_added, uploaded=report.notes_uploaded,
        ))
        return report

    # -- understanding ------------------------------------------------------
    def notes_about(self, topic_name: str, limit: int = 12) -> list[NoteView]:
        """Stored observations that mention a topic, newest last."""
        topic = find_topic(topic_name)
        needles = [topic_name.strip().casefold()]
        if topic is not None:
            needles.extend(keyword.casefold() for keyword in topic.keywords)
        needles = [needle for needle in needles if needle]
        matched: list[NoteView] = []
        for record in self._observation_records():
            text = str(record.get("n", "")).casefold()
            if any(needle in text for needle in needles):
                matched.append(NoteView.from_record(record))
        return matched[-limit:]

    def reflect(self, topic_name: str) -> Reflection | None:
        """Summarise what has been collected into Harold's own words."""
        topic = find_topic(topic_name)
        name = topic.name if topic else topic_name.strip()
        if not name:
            return None
        domain = topic.domain if topic else "External"
        views = self.notes_about(name)
        reflection = build_reflection(
            name, f"{UNDERSTANDING_ROOT}/{domain}", views,
            model=self.model if callable(self.model) else None,
            use_model=self.config.use_model and callable(self.model),
        )
        if reflection is None:
            return None

        stored = None
        try:
            stored = self.store.add(reflection.as_memory_note(), category=reflection.category)
        except Exception as exc:
            self.journal.append(JournalEntry.create(
                KIND_REFLECTION, topic=name, detail=f"synthesis not stored: {exc}",
            ))
        uploaded = self._upload(stored) if stored else 0
        self.journal.append(JournalEntry.create(
            KIND_REFLECTION, topic=name,
            detail=f"from {len(reflection.note_ids)} note(s)" + ("" if stored else " (already known)"),
            uploaded=uploaded,
        ))
        return reflection

    # -- reporting ----------------------------------------------------------
    def status(self) -> dict[str, object]:
        """Counts and budgets for the status command."""
        observations = self._observation_records()
        syntheses = [
            record for record in self.store.records
            if str(record.get("c", "")).startswith(UNDERSTANDING_ROOT)
        ]
        by_domain: dict[str, int] = {}
        for record in observations:
            domain = str(record.get("c", "")).split("/")[-1]
            by_domain[domain] = by_domain.get(domain, 0) + 1
        journal = self.journal.stats()
        return {
            "observations": len(observations),
            "syntheses": len(syntheses),
            "by_domain": dict(sorted(by_domain.items())),
            "topics_covered": len(self.covered_topics()),
            "topics_total": len(TOPIC_SEEDS),
            "pages_read": journal["pages_read"],
            "reflections": journal["reflections"],
            "ftp_configured": self.store.ftp_configured,
            "remote_usage": self.remote_usage(),
        }

    def remote_usage(self) -> dict[str, int]:
        """Estimated size of the notes against the configured remote file cap."""
        cap = getattr(self.store, "max_remote_bytes", 0) or 0
        if not cap:
            return {}
        used = 0
        for record in self.store.records:
            used += len(json.dumps(record, ensure_ascii=False, separators=(",", ":"))) + 1
        return {"used": used, "cap": int(cap), "percent": int(min(100, used * 100 // cap))}

    def render_status(self) -> str:
        """A readable status block."""
        status = self.status()
        by_domain = status["by_domain"]
        lines = [
            f"Harold has {status['observations']} observation(s) and {status['syntheses']} synthesis(es) in memory.",
            f"Curriculum: {status['topics_covered']} of {status['topics_total']} topics have something recorded.",
            f"Journal: {status['pages_read']} page(s) read, {status['reflections']} reflection(s).",
        ]
        if isinstance(by_domain, dict) and by_domain:
            lines.append("By domain: " + ", ".join(f"{name} ({count})" for name, count in by_domain.items()))
        usage = status["remote_usage"]
        if isinstance(usage, dict) and usage:
            lines.append(
                f"FTP relay: {usage['used']} of {usage['cap']} bytes used ({usage['percent']}%)."
            )
        elif not status["ftp_configured"]:
            lines.append(
                "FTP relay: not configured, so observations live only in local memory "
                "(set MEMORY_FTP_HOST/USER/PASSWORD to sync them)."
            )
        return "\n".join(lines)

    def render_curriculum(self) -> str:
        """The curriculum with a mark next to every topic already studied."""
        covered = self.covered_topics()
        lines: list[str] = []
        current = ""
        for topic in TOPIC_SEEDS:
            if topic.domain != current:
                current = topic.domain
                lines.append(f"{current}/")
            mark = "x" if topic.name in covered else " "
            lines.append(f"  [{mark}] {topic.name}")
        lines.append("")
        lines.append(f"Studied: {len(covered)}/{len(TOPIC_SEEDS)}. "
                     "Run /harold learn to study the next unstudied topics.")
        return "\n".join(lines)
