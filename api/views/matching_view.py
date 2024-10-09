# views.py
from django.utils import timezone, asyncio
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from ..models import Game
from ..matching_serializers import GameCreateSerializer, GameLightSerializer


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def join_room(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    user = request.user

    # Check if the game has a password and if the correct password is provided
    password = request.data.get('password')
    if user == game.host:
        return Response({'error': 'Host cannot join the game.'}, status=status.HTTP_400_BAD_REQUEST)

    if game.password and game.password != password:
        return Response({'error': 'Incorrect password.'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if the room is full
    if game.players.count()+1 >= game.max_players:
        return Response({'error': 'Room is full.'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if the game is open for joining
    if game.status != 'Waiting':
        return Response({'error': 'Game is not open for joining.'}, status=status.HTTP_400_BAD_REQUEST)

    # Add the user to the game
    game.players.add(user)
    game.save()
    return Response({'message': 'Joined the game successfully.'}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)

    # Check if the requesting user is the host
    if game.host != request.user:
        return Response({'error': 'Only the host can start the game.'}, status=status.HTTP_403_FORBIDDEN)

    # Check if the game is in 'Waiting' status
    if game.status != 'Waiting':
        return Response({'error': 'Game cannot be started. Current status: {}'.format(game.status)}, status=status.HTTP_400_BAD_REQUEST)

    # Update the game status to 'Battling' and set the battle start time
    game.status = 'Battling'
    game.battle_start_time = timezone.now()
    game.save()

    return Response({'message': 'Game started successfully.', 'battle_start_time': game.battle_start_time}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_game(request):
    print(request.data)
    serializer = GameCreateSerializer(data=request.data)

    if serializer.is_valid():
        has_password = bool(serializer.validated_data.get('password'))
        game = Game.objects.create(
            host=request.user,
            max_players=serializer.validated_data.get('max_players', 2),
            question_number=serializer.validated_data.get('question_number', 10),
            battle_duration=serializer.validated_data.get('battle_duration', 600),
            password=serializer.validated_data.get('password', ''),
            status='Waiting',
            has_password=has_password
        )
        return Response({'message': 'Game created successfully.', 'game_id': game.id}, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_waiting_games(request):
    # Filter games that are in 'Waiting' status
    games = Game.objects.filter(status='Waiting')
    serializer = GameLightSerializer(games, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def retrieve_game(request, game_id):
    # Fetch the specific game by ID
    game = get_object_or_404(Game, id=game_id)
    serializer = GameLightSerializer(game)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)

    # Check if the requesting user is the host
    if game.host != request.user:
        return Response({'error': 'Only the host can delete the game.'}, status=status.HTTP_403_FORBIDDEN)

    # Delete the game
    game.delete()
    return Response({'message': 'Game deleted successfully.'}, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wait_for_game_start(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    timeout = 30  # Maximum time to hold the request (in seconds)
    poll_interval = 0.5  # Time between checks (in seconds)
    elapsed_time = 0

    if game.status != 'Waiting':
        return Response({'status': game.status}, status=status.HTTP_200_OK)

    while elapsed_time < timeout:
        game.refresh_from_db()
        if game.status != 'Waiting':
            return Response({'status': game.status}, status=status.HTTP_200_OK)
        time.sleep(poll_interval)
        elapsed_time += poll_interval

    return Response({'status': 'Waiting'}, status=status.HTTP_200_OK)