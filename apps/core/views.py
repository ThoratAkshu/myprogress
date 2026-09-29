from rest_framework.views import APIView
from rest_framework.response import Response
class HealthCheckAPIView(APIView):
    authentication_classes = []
    permission_classes = []
    def get(self, request):
        return Response({
            "status": "success",
            "message": "MyProjects Backend Running 🚀",
            "version": "v1"
        })