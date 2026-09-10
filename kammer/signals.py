"""Broadcast newly created messages to the room's subscribers.

Only creation is announced from here. Appends use a queryset ``update()`` (no
``post_save``), and ``finishMessage`` broadcasts explicitly, so widening this
receiver to every save would announce a finish twice.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from kammer import models
from kammer.channels import MessageSignal, message_channel, room_group
from kammer.enums import RoomEventKind

logger = logging.getLogger(__name__)


@receiver(post_save, sender=models.Message)
def message_signal(sender, instance=None, created=False, **kwargs):
    """Publish a message onto its room's channel when it is first written."""
    if not instance or not created:
        return
    logger.debug("Broadcasting message %s to room %s", instance.id, instance.room_id)
    message_channel.broadcast_on_commit(MessageSignal(kind=RoomEventKind.MESSAGE_CREATED, message=instance.id), [room_group(instance.room_id)])
