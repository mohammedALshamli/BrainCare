from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.core.serializers import ErrorResponseSerializer

from .serializers import (
    LoginResponseSerializer,
    LoginSerializer,
    LogoutResponseSerializer,
    LogoutSerializer,
    RegisterSerializer,
    UserSerializer,
)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @extend_schema(
        summary="Register a user",
        request=RegisterSerializer,
        responses={
            201: UserSerializer,
            400: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        auth=[],
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @extend_schema(
        summary="Log in with email and password",
        request=LoginSerializer,
        responses={
            200: LoginResponseSerializer,
            401: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        auth=[],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            # A single response for unknown emails, wrong passwords and
            # disabled accounts avoids disclosing which accounts exist.
            raise AuthenticationFailed("Invalid email or password.")

        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(
        summary="Blacklist a refresh token",
        request=LogoutSerializer,
        responses={
            200: LogoutResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
        },
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_token = serializer.validated_data["refresh"]

        try:
            token = RefreshToken(raw_token)
        except TokenError:
            # Logging out with an expired or malformed token is idempotent.
            return Response({"detail": "Logged out."})

        if str(token.get("user_id")) != str(request.user.pk):
            raise ValidationError({"detail": "Invalid token."})

        try:
            token.blacklist()
        except TokenError:
            # Already revoked; treat as success to keep the endpoint idempotent.
            pass

        return Response({"detail": "Logged out."})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Return the authenticated user",
        responses={200: UserSerializer, 401: ErrorResponseSerializer},
    )
    def get(self, request):
        return Response(UserSerializer(request.user).data)
