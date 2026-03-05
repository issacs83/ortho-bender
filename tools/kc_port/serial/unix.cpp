/*
 * unix.cpp - POSIX implementation of serial::Serial::SerialImpl
 * Based on wjwwood/serial (MIT License)
 * Copyright (c) 2012 William Woodall, John Harrison
 */

#if !defined(_WIN32)

#include <stdio.h>
#include <string.h>
#include <sstream>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/time.h>
#include <termios.h>
#include <time.h>
#include <errno.h>
#include <paths.h>

#if defined(__linux__)
# include <linux/serial.h>
#endif

#include "unix.h"

using std::string;
using std::stringstream;
using std::invalid_argument;
using serial::Serial;
using serial::Timeout;
using serial::bytesize_t;
using serial::parity_t;
using serial::stopbits_t;
using serial::flowcontrol_t;
using serial::SerialException;
using serial::PortNotOpenedException;
using serial::IOException;

static inline void millis_to_timespec(const uint32_t millis, timespec *ts) {
  ts->tv_sec = millis / 1e3;
  ts->tv_nsec = (millis - (ts->tv_sec * 1e3)) * 1e6;
}

Serial::SerialImpl::SerialImpl (const string &port, unsigned long baudrate,
                                bytesize_t bytesize, parity_t parity,
                                stopbits_t stopbits, flowcontrol_t flowcontrol)
  : port_ (port), fd_ (-1), is_open_ (false), xonxoff_ (false), rtscts_ (false),
    baudrate_ (baudrate), byte_time_ns_ (0), parity_ (parity),
    bytesize_ (bytesize), stopbits_ (stopbits), flowcontrol_ (flowcontrol)
{
  pthread_mutex_init(&read_mutex, NULL);
  pthread_mutex_init(&write_mutex, NULL);
  if (port_.empty () == false)
    open ();
}

Serial::SerialImpl::~SerialImpl () {
  close();
  pthread_mutex_destroy(&read_mutex);
  pthread_mutex_destroy(&write_mutex);
}

void Serial::SerialImpl::open () {
  if (port_.empty ())
    throw invalid_argument ("Empty port is invalid.");
  if (is_open_ == true)
    throw SerialException ("Serial port already open.");

  fd_ = ::open (port_.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
  if (fd_ == -1) {
    switch (errno) {
    case EINTR:
      open();  // retry on interrupted
      return;
    case ENOENT:
      THROW (IOException, "Serial port not found.");
    default: {
      stringstream ss;
      ss << "Error opening serial port: " << strerror(errno);
      THROW (IOException, ss.str().c_str());
    }
    }
  }

  reconfigurePort();
  is_open_ = true;
}

void Serial::SerialImpl::reconfigurePort () {
  if (fd_ == -1)
    THROW (IOException, "Invalid file descriptor, is the serial port open?");

  struct termios options;
  if (tcgetattr(fd_, &options) == -1)
    THROW (IOException, "Error getting the serial port state.");

  // Input flags - turn off input processing
  options.c_iflag &= ~(IGNBRK | BRKINT | ICRNL | INLCR | PARMRK | INPCK | ISTRIP | IXON);

  // Output flags - turn off output processing
  options.c_oflag &= ~(OCRNL | ONLCR | ONLRET | ONOCR | OFILL | OPOST);
#ifdef OLCUC
  options.c_oflag &= ~OLCUC;
#endif
#ifdef ONOEOT
  options.c_oflag &= ~ONOEOT;
#endif

  // No line processing
  options.c_lflag &= ~(ECHO | ECHONL | ICANON | IEXTEN | ISIG);

  // Set up byte size
  options.c_cflag &= ~CSIZE;
  switch (bytesize_) {
  case fivebits:  options.c_cflag |= CS5; break;
  case sixbits:   options.c_cflag |= CS6; break;
  case sevenbits: options.c_cflag |= CS7; break;
  case eightbits: options.c_cflag |= CS8; break;
  default: throw invalid_argument ("invalid char len");
  }

  // Stop bits
  if (stopbits_ == stopbits_one)
    options.c_cflag &= ~CSTOPB;
  else if (stopbits_ == stopbits_one_point_five || stopbits_ == stopbits_two)
    options.c_cflag |= CSTOPB;

  // Parity
  options.c_iflag &= ~(INPCK | ISTRIP);
  if (parity_ == parity_none)
    options.c_cflag &= ~PARENB;
  else if (parity_ == parity_even) {
    options.c_cflag &= ~PARODD;
    options.c_cflag |= PARENB;
  } else if (parity_ == parity_odd) {
    options.c_cflag |= (PARENB | PARODD);
  }
#ifdef CMSPAR
  else if (parity_ == parity_mark) {
    options.c_cflag |= (PARENB | CMSPAR | PARODD);
  } else if (parity_ == parity_space) {
    options.c_cflag |= (PARENB | CMSPAR);
    options.c_cflag &= ~PARODD;
  }
#endif

  // Flow control
  xonxoff_ = false;
  rtscts_ = false;
  if (flowcontrol_ == flowcontrol_software) {
    options.c_iflag |= (IXON | IXOFF);
    xonxoff_ = true;
  } else if (flowcontrol_ == flowcontrol_hardware) {
#ifdef CRTSCTS
    options.c_cflag |= CRTSCTS;
#endif
    rtscts_ = true;
  }

  // Enable receiver, ignore modem control lines
  options.c_cflag |= (CLOCAL | CREAD);

  // Baud rate
  speed_t baud;
  switch (baudrate_) {
  case 0:      baud = B0;      break;
  case 50:     baud = B50;     break;
  case 75:     baud = B75;     break;
  case 110:    baud = B110;    break;
  case 134:    baud = B134;    break;
  case 150:    baud = B150;    break;
  case 200:    baud = B200;    break;
  case 300:    baud = B300;    break;
  case 600:    baud = B600;    break;
  case 1200:   baud = B1200;   break;
  case 1800:   baud = B1800;   break;
  case 2400:   baud = B2400;   break;
  case 4800:   baud = B4800;   break;
  case 9600:   baud = B9600;   break;
  case 19200:  baud = B19200;  break;
  case 38400:  baud = B38400;  break;
  case 57600:  baud = B57600;  break;
  case 115200: baud = B115200; break;
  case 230400: baud = B230400; break;
#ifdef B460800
  case 460800: baud = B460800; break;
#endif
#ifdef B500000
  case 500000: baud = B500000; break;
#endif
#ifdef B576000
  case 576000: baud = B576000; break;
#endif
#ifdef B921600
  case 921600: baud = B921600; break;
#endif
#ifdef B1000000
  case 1000000: baud = B1000000; break;
#endif
  default:
    // Try custom baud rate
#if defined(__linux__) && defined (TIOCSSERIAL)
    {
      struct serial_struct ser;
      if (::ioctl (fd_, TIOCGSERIAL, &ser) != -1) {
        ser.custom_divisor = ser.baud_base / (int)baudrate_;
        ser.flags &= ~ASYNC_SPD_MASK;
        ser.flags |= ASYNC_SPD_CUST;
        if (::ioctl (fd_, TIOCSSERIAL, &ser) == -1)
          THROW (IOException, "Error setting custom baud rate.");
      }
    }
#endif
    baud = B38400;
  }

  cfsetispeed(&options, baud);
  cfsetospeed(&options, baud);

  // VMIN/VTIME for non-blocking read
  options.c_cc[VMIN] = 0;
  options.c_cc[VTIME] = 0;

  if (tcsetattr(fd_, TCSANOW, &options) != 0)
    THROW (IOException, "Error setting serial port attributes.");

  // Calculate byte time for waitByteTimes
  uint32_t bit_time_ns = 1e9 / baudrate_;
  byte_time_ns_ = bit_time_ns * (1 + static_cast<uint32_t>(bytesize_) +
                    static_cast<uint32_t>(parity_ != parity_none) +
                    static_cast<uint32_t>(stopbits_));
}

void Serial::SerialImpl::close () {
  if (is_open_ == true) {
    if (fd_ != -1) {
      int ret = ::close (fd_);
      if (ret == 0)
        fd_ = -1;
      else
        THROW (IOException, "Error closing serial port.");
    }
    is_open_ = false;
  }
}

bool Serial::SerialImpl::isOpen () const { return is_open_; }

size_t Serial::SerialImpl::available () {
  if (!is_open_) return 0;
  int count = 0;
  if (::ioctl (fd_, FIONREAD, &count) == -1)
    THROW (IOException, "Error checking available bytes.");
  return static_cast<size_t>(count);
}

bool Serial::SerialImpl::waitReadable (uint32_t timeout) {
  fd_set readfds;
  FD_ZERO (&readfds);
  FD_SET (fd_, &readfds);
  timespec timeout_ts;
  millis_to_timespec(timeout, &timeout_ts);
  int r = pselect (fd_ + 1, &readfds, NULL, NULL, &timeout_ts, NULL);
  if (r < 0) {
    if (errno == EINTR) return false;
    THROW (IOException, "Error in waitReadable.");
  }
  return (r > 0);
}

void Serial::SerialImpl::waitByteTimes (size_t count) {
  timespec wait_time = { 0, static_cast<long>(byte_time_ns_ * count) };
  pselect (0, NULL, NULL, NULL, &wait_time, NULL);
}

size_t Serial::SerialImpl::read (uint8_t *buf, size_t size) {
  if (!is_open_) throw PortNotOpenedException ("Serial::read");
  fd_set readfds;
  size_t bytes_read = 0;

  // Calculate total timeout
  uint32_t total_timeout_ms = timeout_.read_timeout_constant +
      timeout_.read_timeout_multiplier * static_cast<uint32_t>(size);

  timespec total_ts;
  millis_to_timespec(total_timeout_ms, &total_ts);

  timespec start_ts;
  clock_gettime(CLOCK_MONOTONIC, &start_ts);

  while (bytes_read < size) {
    // Check total timeout
    timespec now_ts;
    clock_gettime(CLOCK_MONOTONIC, &now_ts);
    long elapsed_ms = (now_ts.tv_sec - start_ts.tv_sec) * 1000 +
                      (now_ts.tv_nsec - start_ts.tv_nsec) / 1000000;
    if (total_timeout_ms > 0 && elapsed_ms >= (long)total_timeout_ms)
      break;

    uint32_t remaining_ms = total_timeout_ms - elapsed_ms;
    timespec sel_ts;
    millis_to_timespec(remaining_ms > 100 ? 100 : remaining_ms, &sel_ts);

    FD_ZERO (&readfds);
    FD_SET (fd_, &readfds);

    int r = pselect (fd_ + 1, &readfds, NULL, NULL, &sel_ts, NULL);
    if (r < 0) {
      if (errno == EINTR) continue;
      THROW (IOException, "Error in read select.");
    }
    if (r == 0) {
      // Timeout on this select, check total
      continue;
    }

    if (FD_ISSET(fd_, &readfds)) {
      ssize_t result = ::read (fd_, buf + bytes_read, size - bytes_read);
      if (result == -1) {
        if (errno == EINTR) continue;
        THROW (IOException, "Error reading from serial port.");
      }
      if (result == 0) break;  // EOF
      bytes_read += result;
    }
  }
  return bytes_read;
}

size_t Serial::SerialImpl::write (const uint8_t *data, size_t length) {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::write");

  fd_set writefds;
  size_t bytes_written = 0;

  uint32_t total_timeout_ms = timeout_.write_timeout_constant +
      timeout_.write_timeout_multiplier * static_cast<uint32_t>(length);

  timespec start_ts;
  clock_gettime(CLOCK_MONOTONIC, &start_ts);

  while (bytes_written < length) {
    timespec now_ts;
    clock_gettime(CLOCK_MONOTONIC, &now_ts);
    long elapsed_ms = (now_ts.tv_sec - start_ts.tv_sec) * 1000 +
                      (now_ts.tv_nsec - start_ts.tv_nsec) / 1000000;
    if (total_timeout_ms > 0 && elapsed_ms >= (long)total_timeout_ms)
      break;

    FD_ZERO (&writefds);
    FD_SET (fd_, &writefds);
    timespec sel_ts;
    millis_to_timespec(100, &sel_ts);

    int r = pselect (fd_ + 1, NULL, &writefds, NULL, &sel_ts, NULL);
    if (r < 0) {
      if (errno == EINTR) continue;
      THROW (IOException, "Error in write select.");
    }

    if (FD_ISSET(fd_, &writefds)) {
      ssize_t result = ::write (fd_, data + bytes_written, length - bytes_written);
      if (result == -1) {
        if (errno == EINTR) continue;
        THROW (IOException, "Error writing to serial port.");
      }
      bytes_written += result;
    }
  }
  return bytes_written;
}

void Serial::SerialImpl::setPort (const string &port) { port_ = port; }
string Serial::SerialImpl::getPort () const { return port_; }

void Serial::SerialImpl::setTimeout (serial::Timeout &timeout) {
  timeout_ = timeout;
  if (is_open_) reconfigurePort ();
}

serial::Timeout Serial::SerialImpl::getTimeout () const { return timeout_; }
void Serial::SerialImpl::setBaudrate (unsigned long baudrate) { baudrate_ = baudrate; if (is_open_) reconfigurePort (); }
unsigned long Serial::SerialImpl::getBaudrate () const { return baudrate_; }
void Serial::SerialImpl::setBytesize (serial::bytesize_t bytesize) { bytesize_ = bytesize; if (is_open_) reconfigurePort (); }
serial::bytesize_t Serial::SerialImpl::getBytesize () const { return bytesize_; }
void Serial::SerialImpl::setParity (serial::parity_t parity) { parity_ = parity; if (is_open_) reconfigurePort (); }
serial::parity_t Serial::SerialImpl::getParity () const { return parity_; }
void Serial::SerialImpl::setStopbits (serial::stopbits_t stopbits) { stopbits_ = stopbits; if (is_open_) reconfigurePort (); }
serial::stopbits_t Serial::SerialImpl::getStopbits () const { return stopbits_; }
void Serial::SerialImpl::setFlowcontrol (serial::flowcontrol_t flowcontrol) { flowcontrol_ = flowcontrol; if (is_open_) reconfigurePort (); }
serial::flowcontrol_t Serial::SerialImpl::getFlowcontrol () const { return flowcontrol_; }

void Serial::SerialImpl::flush () {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::flush");
  tcdrain (fd_);
}

void Serial::SerialImpl::flushInput () {
  if (is_open_ == false) throw PortNotOpenedException("Serial::flushInput");
  tcflush (fd_, TCIFLUSH);
}

void Serial::SerialImpl::flushOutput () {
  if (is_open_ == false) throw PortNotOpenedException("Serial::flushOutput");
  tcflush (fd_, TCOFLUSH);
}

void Serial::SerialImpl::sendBreak (int duration) {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::sendBreak");
  tcsendbreak (fd_, static_cast<int> (duration / 4));
}

void Serial::SerialImpl::setBreak (bool level) {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::setBreak");
  if (level)
    ::ioctl (fd_, TIOCSBRK);
  else
    ::ioctl (fd_, TIOCCBRK);
}

void Serial::SerialImpl::setRTS (bool level) {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::setRTS");
  int command = TIOCM_RTS;
  if (level)
    ::ioctl (fd_, TIOCMBIS, &command);
  else
    ::ioctl (fd_, TIOCMBIC, &command);
}

void Serial::SerialImpl::setDTR (bool level) {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::setDTR");
  int command = TIOCM_DTR;
  if (level)
    ::ioctl (fd_, TIOCMBIS, &command);
  else
    ::ioctl (fd_, TIOCMBIC, &command);
}

bool Serial::SerialImpl::waitForChange () {
#ifdef TIOCMIWAIT
  if (::ioctl(fd_, TIOCMIWAIT, (TIOCM_CTS | TIOCM_DSR | TIOCM_RI | TIOCM_CD)) != 0)
    THROW (IOException, "Error in waitForChange.");
  return true;
#else
  return false;
#endif
}

bool Serial::SerialImpl::getCTS () {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::getCTS");
  int s;
  ::ioctl (fd_, TIOCMGET, &s);
  return (s & TIOCM_CTS) != 0;
}

bool Serial::SerialImpl::getDSR () {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::getDSR");
  int s;
  ::ioctl (fd_, TIOCMGET, &s);
  return (s & TIOCM_DSR) != 0;
}

bool Serial::SerialImpl::getRI () {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::getRI");
  int s;
  ::ioctl (fd_, TIOCMGET, &s);
  return (s & TIOCM_RI) != 0;
}

bool Serial::SerialImpl::getCD () {
  if (is_open_ == false) throw PortNotOpenedException ("Serial::getCD");
  int s;
  ::ioctl (fd_, TIOCMGET, &s);
  return (s & TIOCM_CD) != 0;
}

void Serial::SerialImpl::readLock () { pthread_mutex_lock(&read_mutex); }
void Serial::SerialImpl::readUnlock () { pthread_mutex_unlock(&read_mutex); }
void Serial::SerialImpl::writeLock () { pthread_mutex_lock(&write_mutex); }
void Serial::SerialImpl::writeUnlock () { pthread_mutex_unlock(&write_mutex); }

#endif // !defined(_WIN32)
