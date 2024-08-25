from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import House

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_house_map(request):
    print('Accessed house')
    user = request.user
    try:
        house = House.objects.get(user=user)
        areas = house.areas.all()
        areas_data = [
            {
                "name": area.name,
                "description": area.description,
                "position_x": area.position_x,
                "position_y": area.position_y,
                "width": area.width,
                "height": area.height,
                "is_unlocked": area.is_unlocked,
            }
            for area in areas
        ]
        return Response({"house_name": house.name, "areas": areas_data})
    except House.DoesNotExist:
        return Response({"error": "House not found"}, status=404)
