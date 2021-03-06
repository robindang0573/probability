# Copyright 2018 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""Tests for dense variational layers."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# Dependency imports
import numpy as np

import tensorflow as tf
import tensorflow_probability as tfp

from tensorflow.python.keras import testing_utils

tfd = tfp.distributions


class Counter(object):
  """Helper class to manage incrementing a counting `int`."""

  def __init__(self):
    self._value = -1

  @property
  def value(self):
    return self._value

  def __call__(self):
    self._value += 1
    return self._value


class MockDistribution(tfd.Independent):
  """Monitors layer calls to the underlying distribution."""

  def __init__(self, result_sample, result_log_prob, loc=None, scale=None):
    self.result_sample = result_sample
    self.result_log_prob = result_log_prob
    self.result_loc = loc
    self.result_scale = scale
    self.result_distribution = tfd.Normal(loc=0.0, scale=1.0)
    if loc is not None and scale is not None:
      self.result_distribution = tfd.Normal(loc=self.result_loc,
                                            scale=self.result_scale)
    self.called_log_prob = Counter()
    self.called_sample = Counter()
    self.called_loc = Counter()
    self.called_scale = Counter()

  def log_prob(self, *args, **kwargs):
    self.called_log_prob()
    return self.result_log_prob

  def sample(self, *args, **kwargs):
    self.called_sample()
    return self.result_sample

  @property
  def distribution(self):  # for dummy check on Independent(Normal)
    return self.result_distribution

  @property
  def loc(self):
    self.called_loc()
    return self.result_loc

  @property
  def scale(self):
    self.called_scale()
    return self.result_scale


class MockKLDivergence(object):
  """Monitors layer calls to the divergence implementation."""

  def __init__(self, result):
    self.result = result
    self.args = []
    self.called = Counter()

  def __call__(self, *args, **kwargs):
    self.called()
    self.args.append(args)
    return self.result


class DenseVariational(tf.test.TestCase):

  def _testKerasLayer(self, layer_class):
    def kernel_posterior_fn(dtype, shape, name, trainable, add_variable_fn):
      """Set trivially. The function is required to instantiate layer."""
      del name, trainable, add_variable_fn  # unused
      # Deserialized Keras objects do not perform lexical scoping. Any modules
      # that the function requires must be imported within the function.
      import tensorflow as tf  # pylint: disable=g-import-not-at-top,redefined-outer-name,reimported
      import tensorflow_probability as tfp  # pylint: disable=g-import-not-at-top,redefined-outer-name,reimported
      tfd = tfp.distributions  # pylint: disable=redefined-outer-name

      dist = tfd.Normal(loc=tf.zeros(shape, dtype), scale=tf.ones(shape, dtype))
      batch_ndims = tf.size(dist.batch_shape_tensor())
      return tfd.Independent(dist, reinterpreted_batch_ndims=batch_ndims)

    kwargs = {'units': 3,
              'kernel_posterior_fn': kernel_posterior_fn,
              'kernel_prior_fn': None,
              'bias_posterior_fn': None,
              'bias_prior_fn': None}
    with tf.keras.utils.CustomObjectScope({layer_class.__name__: layer_class}):
      with self.test_session():
        testing_utils.layer_test(
            layer_class,
            kwargs=kwargs,
            input_shape=(3, 2))
        testing_utils.layer_test(
            layer_class,
            kwargs=kwargs,
            input_shape=(None, None, 2))

  def _testKLPenaltyKernel(self, layer_class):
    with self.test_session():
      layer = layer_class(units=2)
      inputs = tf.random_uniform([2, 3], seed=1)

      # No keys.
      input_dependent_losses = layer.get_losses_for(inputs=None)
      self.assertEqual(len(layer.losses), 0)
      self.assertListEqual(layer.losses, input_dependent_losses)

      _ = layer(inputs)

      # Yes keys.
      input_dependent_losses = layer.get_losses_for(inputs=None)
      self.assertEqual(len(layer.losses), 1)
      self.assertEqual(layer.losses[0].shape, ())
      self.assertListEqual(layer.losses, input_dependent_losses)

  def _testKLPenaltyBoth(self, layer_class):
    with self.test_session():
      layer = layer_class(
          units=2,
          bias_posterior_fn=tfp.layers.default_mean_field_normal_fn(),
          bias_prior_fn=tfp.layers.default_multivariate_normal_fn)
      inputs = tf.random_uniform([2, 3], seed=1)

      # No keys.
      input_dependent_losses = layer.get_losses_for(inputs=None)
      self.assertEqual(len(layer.losses), 0)
      self.assertListEqual(layer.losses, input_dependent_losses)

      _ = layer(inputs)

      # Yes keys.
      input_dependent_losses = layer.get_losses_for(inputs=None)
      self.assertEqual(len(layer.losses), 2)
      self.assertEqual(layer.losses[0].shape, ())
      self.assertEqual(layer.losses[1].shape, ())
      self.assertListEqual(layer.losses, input_dependent_losses)

  def _testDenseSetUp(self, layer_class, batch_size, in_size, out_size,
                      **kwargs):
    seed = Counter()
    inputs = tf.random_uniform([batch_size, in_size], seed=seed())

    kernel_size = [in_size, out_size]
    kernel_posterior = MockDistribution(
        loc=tf.random_uniform(kernel_size, seed=seed()),
        scale=tf.random_uniform(kernel_size, seed=seed()),
        result_log_prob=tf.random_uniform(kernel_size, seed=seed()),
        result_sample=tf.random_uniform(kernel_size, seed=seed()))
    kernel_prior = MockDistribution(
        result_log_prob=tf.random_uniform(kernel_size, seed=seed()),
        result_sample=tf.random_uniform(kernel_size, seed=seed()))
    kernel_divergence = MockKLDivergence(
        result=tf.random_uniform([], seed=seed()))

    bias_size = [out_size]
    bias_posterior = MockDistribution(
        result_log_prob=tf.random_uniform(bias_size, seed=seed()),
        result_sample=tf.random_uniform(bias_size, seed=seed()))
    bias_prior = MockDistribution(
        result_log_prob=tf.random_uniform(bias_size, seed=seed()),
        result_sample=tf.random_uniform(bias_size, seed=seed()))
    bias_divergence = MockKLDivergence(
        result=tf.random_uniform([], seed=seed()))

    layer = layer_class(
        units=out_size,
        kernel_posterior_fn=lambda *args: kernel_posterior,
        kernel_posterior_tensor_fn=lambda d: d.sample(seed=42),
        kernel_prior_fn=lambda *args: kernel_prior,
        kernel_divergence_fn=kernel_divergence,
        bias_posterior_fn=lambda *args: bias_posterior,
        bias_posterior_tensor_fn=lambda d: d.sample(seed=43),
        bias_prior_fn=lambda *args: bias_prior,
        bias_divergence_fn=bias_divergence,
        **kwargs)

    outputs = layer(inputs)

    kl_penalty = layer.get_losses_for(inputs=None)
    return (kernel_posterior, kernel_prior, kernel_divergence,
            bias_posterior, bias_prior, bias_divergence,
            layer, inputs, outputs, kl_penalty)

  def testKerasLayerReparameterization(self):
    self._testKerasLayer(tfp.layers.DenseReparameterization)

  def testKerasLayerLocalReparameterization(self):
    self._testKerasLayer(tfp.layers.DenseLocalReparameterization)

  def testKerasLayerFlipout(self):
    self._testKerasLayer(tfp.layers.DenseFlipout)

  def testKLPenaltyKernelReparameterization(self):
    self._testKLPenaltyKernel(tfp.layers.DenseReparameterization)

  def testKLPenaltyKernelLocalReparameterization(self):
    self._testKLPenaltyKernel(tfp.layers.DenseLocalReparameterization)

  def testKLPenaltyKernelFlipout(self):
    self._testKLPenaltyKernel(tfp.layers.DenseFlipout)

  def testKLPenaltyBothReparameterization(self):
    self._testKLPenaltyBoth(tfp.layers.DenseReparameterization)

  def testKLPenaltyBothLocalReparameterization(self):
    self._testKLPenaltyBoth(tfp.layers.DenseLocalReparameterization)

  def testKLPenaltyBothFlipout(self):
    self._testKLPenaltyBoth(tfp.layers.DenseFlipout)

  def testDenseReparameterization(self):
    batch_size, in_size, out_size = 2, 3, 4
    with self.test_session() as sess:
      (kernel_posterior, kernel_prior, kernel_divergence,
       bias_posterior, bias_prior, bias_divergence, layer, inputs,
       outputs, kl_penalty) = self._testDenseSetUp(
           tfp.layers.DenseReparameterization,
           batch_size, in_size, out_size)

      expected_outputs = (
          tf.matmul(inputs, kernel_posterior.result_sample) +
          bias_posterior.result_sample)

      [
          expected_outputs_, actual_outputs_,
          expected_kernel_, actual_kernel_,
          expected_kernel_divergence_, actual_kernel_divergence_,
          expected_bias_, actual_bias_,
          expected_bias_divergence_, actual_bias_divergence_,
      ] = sess.run([
          expected_outputs, outputs,
          kernel_posterior.result_sample, layer.kernel_posterior_tensor,
          kernel_divergence.result, kl_penalty[0],
          bias_posterior.result_sample, layer.bias_posterior_tensor,
          bias_divergence.result, kl_penalty[1],
      ])

      self.assertAllClose(
          expected_kernel_, actual_kernel_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_bias_, actual_bias_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_outputs_, actual_outputs_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_kernel_divergence_, actual_kernel_divergence_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_bias_divergence_, actual_bias_divergence_,
          rtol=1e-6, atol=0.)

      self.assertAllEqual(
          [[kernel_posterior, kernel_prior, kernel_posterior.result_sample]],
          kernel_divergence.args)

      self.assertAllEqual(
          [[bias_posterior, bias_prior, bias_posterior.result_sample]],
          bias_divergence.args)

  def testDenseLocalReparameterization(self):
    batch_size, in_size, out_size = 2, 3, 4
    with self.test_session() as sess:
      (kernel_posterior, kernel_prior, kernel_divergence,
       bias_posterior, bias_prior, bias_divergence, layer, inputs,
       outputs, kl_penalty) = self._testDenseSetUp(
           tfp.layers.DenseLocalReparameterization,
           batch_size, in_size, out_size)

      expected_kernel_posterior_affine = tfd.Normal(
          loc=tf.matmul(inputs, kernel_posterior.result_loc),
          scale=tf.matmul(
              inputs**2., kernel_posterior.result_scale**2)**0.5)
      expected_kernel_posterior_affine_tensor = (
          expected_kernel_posterior_affine.sample(seed=42))
      expected_outputs = (expected_kernel_posterior_affine_tensor +
                          bias_posterior.result_sample)

      [
          expected_outputs_, actual_outputs_,
          expected_kernel_divergence_, actual_kernel_divergence_,
          expected_bias_, actual_bias_,
          expected_bias_divergence_, actual_bias_divergence_,
      ] = sess.run([
          expected_outputs, outputs,
          kernel_divergence.result, kl_penalty[0],
          bias_posterior.result_sample, layer.bias_posterior_tensor,
          bias_divergence.result, kl_penalty[1],
      ])

      self.assertAllClose(
          expected_bias_, actual_bias_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_outputs_, actual_outputs_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_kernel_divergence_, actual_kernel_divergence_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_bias_divergence_, actual_bias_divergence_,
          rtol=1e-6, atol=0.)

      self.assertAllEqual(
          [[kernel_posterior, kernel_prior, None]],
          kernel_divergence.args)

      self.assertAllEqual(
          [[bias_posterior, bias_prior, bias_posterior.result_sample]],
          bias_divergence.args)

  def testDenseFlipout(self):
    batch_size, in_size, out_size = 2, 3, 4
    with self.test_session() as sess:
      (kernel_posterior, kernel_prior, kernel_divergence,
       bias_posterior, bias_prior, bias_divergence, layer, inputs,
       outputs, kl_penalty) = self._testDenseSetUp(
           tfp.layers.DenseFlipout,
           batch_size, in_size, out_size, seed=44)

      expected_kernel_posterior_affine = tfd.Normal(
          loc=tf.zeros_like(kernel_posterior.result_loc),
          scale=kernel_posterior.result_scale)
      expected_kernel_posterior_affine_tensor = (
          expected_kernel_posterior_affine.sample(seed=42))

      stream = tfd.SeedStream(layer.seed, salt='DenseFlipout')

      sign_input = tf.random_uniform(
          [batch_size, in_size],
          minval=0,
          maxval=2,
          dtype=tf.int32,
          seed=stream())
      sign_input = tf.cast(2 * sign_input - 1, inputs.dtype)
      sign_output = tf.random_uniform(
          [batch_size, out_size],
          minval=0,
          maxval=2,
          dtype=tf.int32,
          seed=stream())
      sign_output = tf.cast(2 * sign_output - 1, inputs.dtype)
      perturbed_inputs = tf.matmul(
          inputs * sign_input, expected_kernel_posterior_affine_tensor)
      perturbed_inputs *= sign_output

      expected_outputs = tf.matmul(inputs, kernel_posterior.result_loc)
      expected_outputs += perturbed_inputs
      expected_outputs += bias_posterior.result_sample

      [
          expected_outputs_, actual_outputs_,
          expected_kernel_divergence_, actual_kernel_divergence_,
          expected_bias_, actual_bias_,
          expected_bias_divergence_, actual_bias_divergence_,
      ] = sess.run([
          expected_outputs, outputs,
          kernel_divergence.result, kl_penalty[0],
          bias_posterior.result_sample, layer.bias_posterior_tensor,
          bias_divergence.result, kl_penalty[1],
      ])

      self.assertAllClose(
          expected_bias_, actual_bias_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_outputs_, actual_outputs_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_kernel_divergence_, actual_kernel_divergence_,
          rtol=1e-6, atol=0.)
      self.assertAllClose(
          expected_bias_divergence_, actual_bias_divergence_,
          rtol=1e-6, atol=0.)

      self.assertAllEqual(
          [[kernel_posterior, kernel_prior, None]],
          kernel_divergence.args)

      self.assertAllEqual(
          [[bias_posterior, bias_prior, bias_posterior.result_sample]],
          bias_divergence.args)

  def testRandomDenseFlipout(self):
    batch_size, in_size, out_size = 2, 3, 4
    with self.test_session() as sess:
      seed = Counter()
      inputs = tf.random_uniform([batch_size, in_size], seed=seed())

      kernel_posterior = MockDistribution(
          loc=tf.random_uniform(
              [in_size, out_size], seed=seed()),
          scale=tf.random_uniform(
              [in_size, out_size], seed=seed()),
          result_log_prob=tf.random_uniform(
              [in_size, out_size], seed=seed()),
          result_sample=tf.random_uniform(
              [in_size, out_size], seed=seed()))
      bias_posterior = MockDistribution(
          loc=tf.random_uniform(
              [out_size], seed=seed()),
          scale=tf.random_uniform(
              [out_size], seed=seed()),
          result_log_prob=tf.random_uniform(
              [out_size], seed=seed()),
          result_sample=tf.random_uniform(
              [out_size], seed=seed()))
      layer_one = tfp.layers.DenseFlipout(
          units=out_size,
          kernel_posterior_fn=lambda *args: kernel_posterior,
          kernel_posterior_tensor_fn=lambda d: d.sample(seed=42),
          kernel_divergence_fn=None,
          bias_posterior_fn=lambda *args: bias_posterior,
          bias_posterior_tensor_fn=lambda d: d.sample(seed=43),
          bias_divergence_fn=None,
          seed=44)
      layer_two = tfp.layers.DenseFlipout(
          units=out_size,
          kernel_posterior_fn=lambda *args: kernel_posterior,
          kernel_posterior_tensor_fn=lambda d: d.sample(seed=42),
          kernel_divergence_fn=None,
          bias_posterior_fn=lambda *args: bias_posterior,
          bias_posterior_tensor_fn=lambda d: d.sample(seed=43),
          bias_divergence_fn=None,
          seed=45)

      outputs_one = layer_one(inputs)
      outputs_two = layer_two(inputs)

      outputs_one_, outputs_two_ = sess.run([
          outputs_one, outputs_two])

      self.assertLess(np.sum(np.isclose(outputs_one_, outputs_two_)), out_size)

  def testDenseLayersInSequential(self):
    batch_size, in_size, out_size = 2, 3, 4
    inputs = tf.random_uniform([batch_size, in_size])
    net = tf.keras.Sequential([
        tfp.layers.DenseReparameterization(6, activation=tf.nn.relu),
        tfp.layers.DenseFlipout(6, activation=tf.nn.relu),
        tfp.layers.DenseLocalReparameterization(out_size)
    ])
    outputs = net(inputs)

    with self.test_session() as sess:
      sess.run(tf.global_variables_initializer())
      outputs_ = sess.run(outputs)

    self.assertAllEqual(outputs_.shape, [batch_size, out_size])

if __name__ == '__main__':
  tf.test.main()
