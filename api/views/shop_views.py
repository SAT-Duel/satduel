from django.http import JsonResponse

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

import json

from api.models import Pet, Profile, UserStatistics


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def buy_pet(request):
    try:
        data = json.loads(request.body)
        pet_id = data.get("id")
        user = request.user
        pet2 = Pet.objects.get(name="Bessie The Cow")
        print(pet_id, pet2.id)

        try:
            profile = user.infinitequestionstatistics.get()
        except UserStatistics.DoesNotExist:
            return JsonResponse({"error": "User statistics not found."}, status=404)

        # Ensure UserInventory exists
        user_profile = Profile.objects.get(user=user)
        pet = Pet.objects.get(id=pet_id)
        print(pet_id, pet.name)

        if pet in user_profile.pets.all():
            response = 'Purchase failed. You already own this pet!'
            purchased = False
        elif profile.coins >= pet.price:
            profile.coins -= pet.price
            user_profile.pets.add(pet)
            user_profile.save()
            pet_levels = user_profile.user_pet_levels  # Get the current pet levels as a dictionary
            pet_levels[str(pet.id)] = 1  # Add the pet with starting level 1
            user_profile.user_pet_levels = pet_levels  # Update the field with the new value
            profile.save()
            response = 'Purchase successful.'
            purchased = True
        else:
            response = 'Purchase failed. Not enough coins!'
            purchased = False

        return JsonResponse({"message": response, "purchased": purchased})

    except Pet.DoesNotExist:
        return JsonResponse({"error": "Pet not found."}, status=404)
    except Exception as e:
        print(f"Error: {e}")
        return JsonResponse({"error": "Purchase failed."}, status=400)