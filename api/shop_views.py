from django.http import JsonResponse

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

import json

from .models import Pet, UserInventory, UserStatistics


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def buy_pet(request):
    try:
        data = json.loads(request.body)
        pet_id = data.get("id")
        user = request.user
        
        # Fetch the InfiniteQuestionStatistics instance for this user
        try:
            profile = user.infinitequestionstatistics.get()  # Assuming there is only one related InfiniteQuestionStatistics instance per user
        except UserStatistics.DoesNotExist:
            return JsonResponse({"error": "User statistics not found."}, status=404)
        
        # Ensure UserInventory exists
        user_inventory, created = UserInventory.objects.get_or_create(user=user)
        pet = Pet.objects.get(id=pet_id)
        
        if pet in user_inventory.pets.all():
            response = 'Purchase failed. You already own this pet!'
            purchased = False
        elif profile.coins >= pet.price:
            profile.coins -= pet.price
            user_inventory.pets.add(pet)
            user_inventory.save()
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