from django.http import JsonResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.models import Pet, Profile, UserStatistics


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def user_pets(request):
    try:
        # Get the profile and user statistics of the authenticated user
        user_profile = Profile.objects.get(user=request.user)
        user_stats = UserStatistics.objects.get(user=request.user)

        # Get all pets owned by the user
        owned_pets = user_profile.pets.all()

        # Fetch pet levels from user statistics (defaults to level 1 if the pet is not present)
        pet_levels = user_stats.user_pet_levels

        # Build a list of pets with their relevant details including animation data and level
        pets_data = [
            {
                'id': pet.id,
                'name': pet.name,
                'animationData': pet.animation_data,  # Assuming animation_data holds the JSON structure
                'level': pet_levels.get(str(pet.id), 1),  # Default level is 1 if pet not found in JSON
                'price': pet.price  # Include price to calculate upgrade cost on the frontend
            }
            for pet in owned_pets
        ]

        return JsonResponse({'pets': pets_data}, status=200)

    except Profile.DoesNotExist:
        return JsonResponse({'error': 'User profile not found.'}, status=404)

    except UserStatistics.DoesNotExist:
        return JsonResponse({'error': 'User statistics not found.'}, status=404)

    except Exception as e:
        print(f"Error fetching user pets: {e}")
        return JsonResponse({'error': 'An error occurred while fetching user pets.'}, status=500)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def upgrade_pet(request):
    user = request.user
    pet_id = request.data.get("pet_id")

    try:
        # Fetch the pet and the user's profile/statistics
        pet = Pet.objects.get(id=pet_id)
        stats = UserStatistics.objects.get(user=user)
        user_profile = Profile.objects.get(user=user)

        # Get current level of the pet, default to 1 if not owned yet
        current_level = stats.user_pet_levels.get(str(pet_id), 1)
        upgrade_cost = (current_level + 1) * pet.price

        # Check if user has enough coins
        if stats.coins < upgrade_cost:
            return JsonResponse({"status": "error", "message": "Not enough coins to upgrade."}, status=400)

        # Deduct the coins and upgrade the pet
        stats.coins -= upgrade_cost
        stats.user_pet_levels[str(pet_id)] = current_level + 1
        stats.save()

        return JsonResponse({
            "status": "success",
            "new_level": current_level + 1,
            "coins_left": stats.coins,
            "message": f"Your {pet.name} has been upgraded to level {current_level + 1}."
        })

    except Pet.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Pet not found."}, status=404)
    except UserStatistics.DoesNotExist:
        return JsonResponse({"status": "error", "message": "User statistics not found."}, status=404)
    except Exception as e:
        print(f"Error: {e}")
        return JsonResponse({"status": "error", "message": "An error occurred while upgrading the pet."}, status=400)
