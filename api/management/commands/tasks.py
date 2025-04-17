from django.utils import timezone
import pytz
from datetime import timedelta
from api.models import Profile, QuestTemplate, PersonalizedQuest

def generate_user_quests():
    """Generate quests for all users based on their local midnight."""
    for profile in Profile.objects.all():
        try:
            user_tz = pytz.timezone(profile.timezone)
            user_now = timezone.now().astimezone(user_tz)
            # Check if it's midnight in user's timezone (0-1 hour window)
            if user_now.hour == 0:
                # Generate daily quests
                try:
                    daily_template = QuestTemplate.objects.get(
                        goal_type=profile.goal,
                        period_type='daily'
                    )

                    # Check if user already has an active daily quest
                    existing_daily = PersonalizedQuest.objects.filter(
                        user=profile.user,
                        template__period_type='daily',
                        end_time__gt=user_now
                    ).exists()

                    if not existing_daily:
                        PersonalizedQuest.objects.create(
                            user=profile.user,
                            template=daily_template,
                            target=daily_template.generate_target(),
                            reward_coins=daily_template.generate_reward(),
                            start_time=user_now,
                            end_time=user_now + timedelta(days=1)
                        )
                except QuestTemplate.DoesNotExist:
                    pass

                # Generate weekly quests on Monday
                if user_now.weekday() == 0:  # Monday
                    try:
                        weekly_template = QuestTemplate.objects.get(
                            goal_type=profile.goal,
                            period_type='weekly'
                        )

                        # Check if user already has an active weekly quest
                        existing_weekly = PersonalizedQuest.objects.filter(
                            user=profile.user,
                            template__period_type='weekly',
                            end_time__gt=user_now
                        ).exists()

                        if not existing_weekly:
                            PersonalizedQuest.objects.create(
                                user=profile.user,
                                template=weekly_template,
                                target=weekly_template.generate_target(),
                                reward_coins=weekly_template.generate_reward(),
                                start_time=user_now,
                                end_time=user_now + timedelta(days=7)
                            )
                    except QuestTemplate.DoesNotExist:
                        pass

        except Exception as e:
            pass

    # Add this cleanup section at the end
    try:
        # Delete expired quests older than 1 day
        expiration_threshold = timezone.now() - timedelta(days=1)
        expired_quests = PersonalizedQuest.objects.filter(
            end_time__lte=expiration_threshold
        )
        delete_count, _ = expired_quests.delete()
        print(f"Cleaned up {delete_count} expired quests")
    except Exception as e:
        print(f"Error cleaning up quests: {str(e)}")