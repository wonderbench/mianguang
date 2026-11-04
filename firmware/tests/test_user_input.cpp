#include "user_input.h"
#include <cassert>
#include <limits>
#include <iostream>
using namespace sleep_core;

int main() {
  Button key;
  assert(key.update(true, 0) == ButtonEvent::None);
  assert(key.update(false, 6000) == ButtonEvent::None);
  assert(key.update(false, 6030) == ButtonEvent::None); // boot-held ignored
  key.update(true, 6100); key.update(false, 6110); key.update(true, 6120);
  assert(key.update(true, 6150) == ButtonEvent::None);
  key.update(false, 6220);
  assert(key.update(false, 6250) == ButtonEvent::Short);
  assert(key.update(false, 6300) == ButtonEvent::None);
  key.update(true, 7000); key.update(true, 7030);
  key.update(false, 8500);
  assert(key.update(false, 8530) == ButtonEvent::Long);
  key.update(true, 9000); key.update(true, 9030);
  key.update(false, 14000);
  assert(key.update(false, 14030) == ButtonEvent::Auto);
  key.update(true, 0xfffffff0u); key.update(true, 14);
  key.update(false, 100);
  assert(key.update(false, 130) == ButtonEvent::Short);

  AmbientGate gate;
  gate.observe(0, 0); assert(!gate.state(0).known);
  gate.setCalibrated(true); assert(!gate.state(0).known);
  gate.observe(7, 10); assert(!gate.state(10).known);
  gate.observe(5, 20); assert(gate.state(20).known && gate.state(20).dark);
  gate.observe(7, 30); assert(gate.state(30).dark);
  gate.observe(10, 40); assert(gate.state(40).known && !gate.state(40).dark);
  gate.observe(7, 50); assert(!gate.state(50).dark);
  assert(!gate.state(2551).known);
  gate.observe(7, 2551); assert(!gate.state(2551).known);
  gate.observe(0, 2600); assert(gate.state(2600).dark);
  gate.fault(); assert(!gate.state(2600).known);
  gate.observe(7, 2700); assert(!gate.state(2700).known);
  gate.observe(std::numeric_limits<float>::quiet_NaN(), 2800);
  assert(!gate.state(2800).known);
  gate.observe(-1, 2900); assert(!gate.state(2900).known);
  gate.observe(1, 0xfffffff0u); assert(gate.state(50).known);
  gate.setCalibrated(false); assert(!gate.state(50).known);
  std::cout << "user input and ambient tests passed\n";
}
