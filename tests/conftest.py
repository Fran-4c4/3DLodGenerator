"""Select wheel-native CRS databases before importing geospatial test modules."""
from tools.native_environment import isolate_wheel_proj_data

isolate_wheel_proj_data()
