# python3
# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Deterministic velocity fields for advection-diffusion equation."""
import enum
from typing import Any, Tuple, TypeVar
import warnings

import numpy as np
from datadrivenpdes.core import grids
import tensorflow as tf


class VelocityComponent(enum.Enum):
  """Enum representing valid velocity field components."""
  X = 1
  Y = 2


class VelocityField:
  """Base class for implementations of velocity fields.

  Defines methods get_velocity_x and get_velocity_y used by equation classes.
  """

  def get_velocity_x(
      self,
      t: float,
      grid: grids.Grid,
      shift: Tuple[int, int] = (0, 0),
      face_average: bool = False,
  ) -> tf.Tensor:
    """Returns a tensor holding x component of the velocity field.

    Args:
      t: Time at which to evaluate the velocity fields.
      grid: Grid object on which the field is evaluated.
      shift: Number of half-step shifts on the grid along x and y axes.
      face_average: If true, return the average over the face of a grid cell
        rather than point values directly.

    Returns:
      x component of the velocity field as tensor with
      shape=[grid.size_x, grid.size_y] and dtype=float64.
    """
    raise NotImplementedError

  def get_velocity_y(
      self,
      t: float,
      grid: grids.Grid,
      shift: Tuple[int, int] = (0, 0),
      face_average: bool = False,
  ) -> tf.Tensor:
    """Returns a tensor holding y component of the velocity field.

    Args:
      t: Time at which to evaluate the velocity fields.
      grid: Grid object on which the field is evaluated.
      shift: Number of half-step shifts on the grid along x and y axes.
      face_average: If true, return the average over the face of a grid cell
        rather than point values directly.

    Returns:
      y component of the velocity field as tensor with
      shape=[grid.size_x, grid.size_y] and dtype=float64.
    """
    raise NotImplementedError


def _block_average_of_sin(k, x, phi, grid_step):
  """Integral of sin(k * x + phi) over [x - grid_step/2, x + grid_step/2]."""
  # Based on the indefinite integral:
  #   \int sin(k x + phi) dx = -cos(k x + phi) / k + C
  x0 = x - grid_step / 2
  x1 = x + grid_step / 2
  with warnings.catch_warnings():
    warnings.simplefilter('ignore')  # ignore warnings for division by 0
    return np.where(
        k == 0,
        np.sin(phi),
        1 / (grid_step * k) * (np.cos(k * x0 + phi) - np.cos(k * x1 + phi))
    )


T = TypeVar('T')


class ConstantVelocityField(VelocityField):
  """Implementation of a random, divergence-less constant velocity field.

  Attributes:
    amplitudes: ndarray of float amplitudes of sin() terms.
    x_wavenumbers: ndarray of integer spatial x-frequencies of sin() terms.
    y_wavenumbers: ndarray of integer spatial y-frequencies of sin() terms.
    phase_shifts: ndarray of float phase shifts of sin() terms.
  """

  def __init__(self,
               x_wavenumbers: np.ndarray,
               y_wavenumbers: np.ndarray,
               amplitudes: np.ndarray,
               phase_shifts: np.ndarray):
    """Constructor."""
    if not (x_wavenumbers.shape == y_wavenumbers.shape ==
            amplitudes.shape == phase_shifts.shape):
      raise ValueError('mismatched shapes')
    self.x_wavenumbers = x_wavenumbers
    self.y_wavenumbers = y_wavenumbers
    self.amplitudes = amplitudes
    self.phase_shifts = phase_shifts

  @property
  def num_terms(self) -> int:
    """Integer number of sin() terms used to initialize random field."""
    return self.amplitudes.size

  @property
  def max_periods(self):
    """Integer limit on how many periods fit in 2 * pi domain."""
    return max(abs(self.x_wavenumbers).max(), abs(self.y_wavenumbers).max())

  def evaluate(
      self,
      component: VelocityComponent,
      grid: grids.Grid,
      shift: Tuple[int, int] = (0, 0),
  ) -> np.ndarray:
    """Evaluate this velocity field on the given grid.

    Generates numerical values of the field on the mesh generated by the grid.
    Shift argument can be used to evaluate the velocity field on the boundary.

    Args:
      component: Component of the velocity to be evaluated.
      grid: Grid object defining the mesh on which velocity is evaluated.
      shift: Number of half-step shifts on the grid along x and y axes.

    Returns:
      Float64 array with shape [X, Y] giving requested velocity field component.
    """

    x, y = grid.get_mesh(shift)

    # We use the axis order [x, y, term]
    x = x[..., np.newaxis]
    y = y[..., np.newaxis]

    k_x = 2 * np.pi * self.x_wavenumbers / grid.length_x
    k_y = 2 * np.pi * self.y_wavenumbers / grid.length_y

    phase = k_x * x + k_y * y + self.phase_shifts
    calculate_vx = component is VelocityComponent.X
    scale = self.y_wavenumbers if calculate_vx else -self.x_wavenumbers
    return (scale * self.amplitudes * np.sin(phase)).sum(axis=-1)

  def face_average(
      self,
      component: VelocityComponent,
      grid: grids.Grid,
      shift: Tuple[int, int] = (0, 0),
  ) -> np.ndarray:
    """Calculate the cell-averaged velocity field over the given cell-face.

    Like evaluate(), but the resulting field is (exactly) averaged over the
    cell face perpendicular to the velocity component.

    Args:
      component: Component of the velocity to be evaluated.
      grid: Grid object defining the mesh on which velocity is evaluated.
      shift: Number of half-step shifts on the grid along x and y axes.

    Returns:
      Float64 array with shape [X, Y] giving requested velocity field component.
    """
    x, y = grid.get_mesh(shift)

    # We use the axis order [x, y, term]
    x = x[..., np.newaxis]
    y = y[..., np.newaxis]

    k_x = 2 * np.pi * self.x_wavenumbers / grid.length_x  # shape: [term]
    k_y = 2 * np.pi * self.y_wavenumbers / grid.length_y  # shape: [term]

    phase = self.phase_shifts
    calculate_vx = component is VelocityComponent.X
    scale = self.y_wavenumbers if calculate_vx else -self.x_wavenumbers
    if calculate_vx:
      waves = _block_average_of_sin(k_y, y, k_x * x + phase, grid.step)
    else:
      waves = _block_average_of_sin(k_x, x, k_y * y + phase, grid.step)
    return (scale * self.amplitudes * waves).sum(axis=-1)

  def get_velocity_x(
      self,
      t: float,
      grid: grids.Grid,
      shift: Tuple[int, int] = (0, 0),
      face_average: bool = False,
  ) -> tf.Tensor:
    """See base class."""
    del t  # constant velocity field is time independent
    method = self.face_average if face_average else self.evaluate
    velocity_x = method(VelocityComponent.X, grid, shift)
    return velocity_x

  def get_velocity_y(
      self,
      t: float,
      grid: grids.Grid,
      shift: Tuple[int, int] = (0, 0),
      face_average: bool = False,
  ) -> tf.Tensor:
    """See base class."""
    del t  # constant velocity field is time independent
    method = self.face_average if face_average else self.evaluate
    velocity_y = method(VelocityComponent.Y, grid, shift)
    return velocity_y

  @classmethod
  def from_seed(
      cls,
      max_periods: int = 4,
      power_law: float = -3,
      seed: int = None,
      normalize: bool = True,
  ) -> VelocityField:
    """Creates an instance of a ConstantVelocityField from a random seed.

    Uses a power-law distribution with a hard cutoff, namely with amplitudes
    scaled by (k+1)**n where k=(k_x**2+k_y**2)**0.5 and n is some (negative)
    constant.

    Args:
      max_periods: maximum period to use for the signal.
      power_law: power law for decay.
      seed: Seed for random number generator.
      normalize: If True, normalize the field to have a maximum velocity of
        approximately one.

    Returns:
      ConstantVelocityField object.
    """
    rnd_gen = np.random.RandomState(seed=seed)
    ks = np.arange(-max_periods, max_periods + 1)
    k_x, k_y = [k.ravel() for k in np.meshgrid(ks, ks, indexing='ij')]
    scale = ((k_x ** 2 + k_y ** 2) ** 0.5 + 1) ** float(power_law)
    amplitudes = scale * rnd_gen.random_sample(size=scale.shape)
    phase_shifts = rnd_gen.random_sample(size=scale.shape) * np.pi * 2.
    vfield = cls(k_x, k_y, amplitudes, phase_shifts)
    if normalize:
      vfield = vfield.normalize()
    return vfield

  def normalize(self: T, test_grid_size: int = 256) -> T:
    """Return a new field with maximum velocity scaled to approximately one."""
    length = 2 * np.pi
    step = length / test_grid_size
    test_grid = grids.Grid(test_grid_size, test_grid_size, step)

    v_x = self.evaluate(VelocityComponent.X, test_grid)
    v_y = self.evaluate(VelocityComponent.Y, test_grid)
    v_max = np.sqrt(v_x ** 2 + v_y ** 2).max()
    amplitudes = self.amplitudes / v_max

    return type(self)(self.x_wavenumbers, self.y_wavenumbers,
                      amplitudes, self.phase_shifts)
