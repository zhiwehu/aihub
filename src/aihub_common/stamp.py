"""Recording timestamps: ``[mm:ss]`` for short takes, ``[h:mm:ss]`` for long ones.

Transcribed lines carry a relative timestamp inside the recording. The web
player and the diarizer both need to turn those stamps back into milliseconds,
so the two directions live together and round-trip.
"""

__all__ = ["stamp_ms", "stamp_text"]


def stamp_text(elapsed_ms):
    """Render milliseconds as ``mm:ss`` (under an hour) or ``h:mm:ss``."""
    total = max(0, int(elapsed_ms)) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


def stamp_ms(value):
    """Parse ``mm:ss`` or ``h:mm:ss`` back into milliseconds.

    Raises ``ValueError`` for anything that is not two or three integer fields.
    """
    parts = [int(part) for part in value.split(':')]
    if len(parts) == 2:
        minutes, seconds = parts
        return (minutes * 60 + seconds) * 1000
    hours, minutes, seconds = parts
    return ((hours * 60 + minutes) * 60 + seconds) * 1000
