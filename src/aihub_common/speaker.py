"""Online speaker clustering over segment embeddings.

This is the half of the old ``voicehub/speaker.py`` that contains no model: it
takes 192-d embeddings and assigns them to anonymous speakers (说话人1/2/…).
The embedding half — the SpeechBrain ECAPA loader — lives in ``aihub-models``
because it needs torch.

Both sides need this clusterer: the server tracks speakers live while a
recording runs, and the model service re-clusters a finished recording. Only
labels are kept; embeddings never leave memory and are never written to disk.
There is no cross-recording identity and no name recognition.

Tuning (``AIHUB_`` prefix, with the pre-split ``VOICEHUB_`` names still read as
a fallback):

* ``SPEAKER_THRESHOLD`` (default 0.25) — cosine similarity needed to join an
  existing speaker.
* ``SPEAKER_MAX`` (default 6) — maximum speakers per recording.
* ``SPEAKER_MIN_SECONDS`` (default 1.2) — shorter segments never create a new
  speaker.
"""

import os

import numpy as np

__all__ = ["SpeakerUnavailable", "SpeakerTracker", "normalize"]


class SpeakerUnavailable(RuntimeError):
    def __init__(self, code='speaker_unavailable'):
        self.code = code
        super().__init__(code)


def normalize(vector):
    """Return a unit-length float32 copy, or raise if the vector is degenerate."""
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1e-8:
        raise SpeakerUnavailable('speaker_embedding_invalid')
    return vector / norm


def _env_value(name, default):
    """Read ``AIHUB_<name>``, falling back to the pre-split ``VOICEHUB_<name>``."""
    for prefix in ('AIHUB_', 'VOICEHUB_'):
        raw = os.environ.get(prefix + name)
        if raw is not None:
            return raw
    return default


def _env_float(name, default, low, high):
    try:
        value = float(_env_value(name, default))
    except (TypeError, ValueError):
        return default
    return min(high, max(low, value))


def _env_int(name, default, low, high):
    try:
        value = int(_env_value(name, default))
    except (TypeError, ValueError):
        return default
    return min(high, max(low, value))


class SpeakerTracker:
    """Online cosine clustering of one recording's segment embeddings."""

    def __init__(self, threshold=None, max_speakers=None, min_seconds=None,
                 promote_seconds=0.0):
        self.threshold = (_env_float('SPEAKER_THRESHOLD', .25, .05, .9)
                          if threshold is None
                          else min(.9, max(.05, float(threshold))))
        self.max_speakers = (_env_int('SPEAKER_MAX', 6, 1, 12)
                             if max_speakers is None
                             else min(12, max(1, int(max_speakers))))
        self.min_seconds = (_env_float('SPEAKER_MIN_SECONDS', 1.2, .2, 10)
                            if min_seconds is None
                            else min(10, max(.2, float(min_seconds))))
        self.centroids = []
        self.counts = []
        self.first = []
        self.durations = []
        self.promote_seconds = max(0.0, float(promote_seconds))
        self.pending = []
        self.pending_seconds = 0.0

    @property
    def count(self):
        return len(self.centroids)

    def _add(self, embedding, duration):
        self.pending, self.pending_seconds = [], 0.0
        self.centroids.append(embedding.copy())
        self.counts.append(1)
        self.first.append(len(self.first))
        self.durations.append(duration)
        identity = len(self.centroids)
        return identity, f'说话人{identity}'

    def _join(self, identity, embedding, duration, clear_pending=True):
        if clear_pending:
            self.pending, self.pending_seconds = [], 0.0
        index = identity - 1
        total = self.counts[index]
        centroid = (self.centroids[index] * total + embedding) / (total + 1)
        self.centroids[index] = normalize(centroid)
        self.counts[index] = total + 1
        self.durations[index] += duration
        return identity, f'说话人{identity}'

    def assign(self, embedding, duration):
        """Return ``(speaker_id, '说话人N')`` for one segment."""
        embedding = normalize(embedding)
        duration = max(0.0, float(duration))
        if not self.centroids:
            return self._add(embedding, duration)
        similarities = np.stack(self.centroids) @ embedding
        best = int(np.argmax(similarities))
        if float(similarities[best]) >= self.threshold:
            return self._join(best + 1, embedding, duration)
        if duration < self.min_seconds or len(self.centroids) >= self.max_speakers:
            return self._join(best + 1, embedding, duration)
        if self.promote_seconds <= 0:
            return self._add(embedding, duration)
        # A new voice has to persist before it becomes a speaker.  This prevents
        # short content/noise windows from creating 3, 4, 5... speakers.
        self.pending.append(embedding.copy())
        self.pending_seconds += duration
        if self.pending_seconds >= self.promote_seconds and len(self.pending) >= 2:
            centroid = normalize(np.stack(self.pending).mean(0))
            identity = len(self.centroids) + 1
            self.centroids.append(centroid)
            self.counts.append(len(self.pending))
            self.first.append(len(self.first))
            self.durations.append(self.pending_seconds)
            self.pending, self.pending_seconds = [], 0.0
            return identity, f'说话人{identity}'
        # Provisional assignment: do not contaminate the existing centroid
        # with an unmatched window, and keep accumulating evidence.
        return best + 1, f'说话人{best + 1}'

    def refine(self):
        """Fold single-segment clusters, then return an old→new id map.

        Called once after the recording stops, when all segments are known.
        A participant represented by only one segment cannot be verified, so
        that segment joins the nearest remaining speaker.  Clusters with two
        or more segments survive.  New ids follow first appearance.
        """
        alias = {identity: identity for identity in range(1, len(self.centroids) + 1)}
        counts = list(self.counts)
        centroids = [c.copy() for c in self.centroids]
        first = list(self.first)
        durations = list(self.durations)
        active = set(alias)

        changed = True
        while len(active) > 1 and changed:
            changed = False
            singletons = sorted(
                (identity for identity in active if counts[identity - 1] == 1),
                key=lambda identity: (durations[identity - 1], identity),
            )
            if not singletons:
                break
            source = singletons[0]
            source_centroid = centroids[source - 1]
            targets = [
                (float(np.dot(source_centroid, centroids[target - 1])), target)
                for target in active if target != source
            ]
            if not targets:
                break
            target = max(targets)[1]
            total = counts[target - 1]
            centroids[target - 1] = normalize(
                (centroids[target - 1] * total + centroids[source - 1]) / (total + 1))
            counts[target - 1] += counts[source - 1]
            durations[target - 1] += durations[source - 1]
            first[target - 1] = min(first[target - 1], first[source - 1])
            alias[source] = target
            for old, value in list(alias.items()):
                if value == source:
                    alias[old] = target
            active.discard(source)
            changed = True

        ordered = sorted(active, key=lambda identity: first[identity - 1])
        renumber = {identity: position + 1 for position, identity in enumerate(ordered)}
        mapping = {}
        for old in range(1, len(self.centroids) + 1):
            resolved = old
            while alias.get(resolved) != resolved:
                resolved = alias[resolved]
            mapping[old] = renumber[resolved]
        return mapping, len(ordered)
