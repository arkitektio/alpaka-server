"""Room rows embed their title + description (pgvector) for the semantic ``search`` filter.

``VectorExtension`` creates ``vector`` in this database (idempotent; each app's migration
carries it so either order works). ``makemigrations`` cannot emit it -- re-add it by hand if
this history is ever regenerated -- and the test suite never runs it (schema is built with
run-syncdb; ``tests/conftest.py`` installs the extension itself). On a daten image without
pgvector it fails here, loudly, which is the right place to fail.

The backfill embeds every existing row in this transaction (a static model, ~1 ms a row); the
in-process healer (``embeddings.healer``, started from ``alpaka_server/asgi.py``) would
otherwise do it within a sweep.
"""

from typing import Any

import pgvector.django.vector
from django.conf import settings
from django.db import migrations, models
from pgvector.django import VectorExtension

BATCH = 500


def backfill_embeddings(apps: Any, schema_editor: Any) -> None:
    """Embed every Room that has text, with the configured model; no-op when disabled."""
    from embeddings import engine

    if not engine.enabled():
        return
    model = apps.get_model("kammer", "Room")
    current = engine.model_id()
    queryset = model._default_manager.exclude(embedding_model=current).order_by("pk").only("pk", "title", "description")
    while True:
        rows = list(queryset[:BATCH])
        if not rows:
            return
        sources = [engine.source_text(row.title, row.description) for row in rows]
        vectors = iter(engine.embed_texts([source for source in sources if source is not None]))
        for row, source in zip(rows, sources, strict=True):
            row.embedding = next(vectors) if source is not None else None
            row.embedding_model = current
        model._default_manager.bulk_update(rows, ["embedding", "embedding_model"])


class Migration(migrations.Migration):
    """Extension, the two columns, the healer's index, and the backfill -- one transaction."""

    dependencies = [
        ("authentikate", "0006_alter_app_identifier_alter_release_unique_together"),
        ("kammer", "0004_alter_agent_room"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        VectorExtension(),
        migrations.AddField(
            model_name="room",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=256, editable=False, help_text="Unit-length embedding of name + description, by the model named in embedding_model; NULL when there is no text to embed", null=True),
        ),
        migrations.AddField(
            model_name="room",
            name="embedding_model",
            field=models.CharField(blank=True, default="", editable=False, help_text="The embedding model that produced `embedding`. Rows whose value differs from the configured model are re-embedded in-process and are excluded from vector search until then", max_length=200),
        ),
        migrations.AddIndex(
            model_name="room",
            index=models.Index(fields=["embedding_model"], name="room_emb_model_idx"),
        ),
        migrations.RunPython(backfill_embeddings, migrations.RunPython.noop),
    ]
