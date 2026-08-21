"""Broadcast newly created messages to the room's subscribers."""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from kammer import models
from kammer.channels import MessageSignal, message_channel

logger = logging.getLogger(__name__)


@receiver(post_save, sender=models.Message)
def message_signal(sender, instance=None, created=False, **kwargs):
    """Publish a message onto its room's channel when it is first written."""
    if not instance or not created:
        return
    logger.debug("Broadcasting message %s to room %s", instance.id, instance.room_id)
    message_channel.broadcast(MessageSignal(message=instance.id), [f"room_{instance.room_id}"])
