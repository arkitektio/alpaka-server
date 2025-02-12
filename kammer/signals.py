import logging

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from kammer import models
from kammer.channels import message_brodcast

logger = logging.getLogger(__name__)
logger.info("Loading signals")


@receiver(post_save, sender=models.Message)
def message_signal(sender, instance=None, **kwargs):
    print("Signal received!")
    if instance:
        print("Message created", instance.id)
        message_brodcast(instance.id, [f"room_{instance.agent.room.id}"])
