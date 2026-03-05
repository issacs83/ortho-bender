/*
 * list_ports_linux.cpp - Linux serial port enumeration
 * Based on wjwwood/serial (MIT License)
 */

#if !defined(_WIN32)

#include <vector>
#include <string>
#include <sstream>
#include <fstream>
#include <cstring>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>

#include "serial.h"

using serial::PortInfo;
using std::vector;
using std::string;

static vector<string> glob_pattern(const string &pattern_dir)
{
    vector<string> result;
    DIR *dir = opendir(pattern_dir.c_str());
    if (dir) {
        struct dirent *entry;
        while ((entry = readdir(dir)) != NULL) {
            if (entry->d_name[0] != '.')
                result.push_back(pattern_dir + "/" + string(entry->d_name));
        }
        closedir(dir);
    }
    return result;
}

static string read_line(const string &path)
{
    std::ifstream ifs(path);
    string line;
    if (ifs.is_open())
        std::getline(ifs, line);
    return line;
}

static string realpath_str(const string &path)
{
    char *rp = realpath(path.c_str(), NULL);
    if (rp) {
        string result(rp);
        free(rp);
        return result;
    }
    return "";
}

static string basename_str(const string &path)
{
    size_t pos = path.rfind('/');
    if (pos != string::npos)
        return path.substr(pos + 1);
    return path;
}

vector<PortInfo>
serial::list_ports()
{
    vector<PortInfo> results;

    // Enumerate /sys/class/tty devices
    vector<string> tty_devices = glob_pattern("/sys/class/tty");

    for (auto &dev_path : tty_devices) {
        string dev_name = basename_str(dev_path);

        // Only include USB serial devices and ACM devices
        string device_path = realpath_str(dev_path + "/device");
        if (device_path.empty())
            continue;

        // Check if it's a USB serial device
        if (device_path.find("usb") == string::npos &&
            device_path.find("acm") == string::npos &&
            dev_name.find("ttyUSB") == string::npos &&
            dev_name.find("ttyACM") == string::npos &&
            dev_name.find("ttyAMA") == string::npos)
            continue;

        PortInfo info;
        info.port = "/dev/" + dev_name;

        // Try to read device description
        string product = read_line(dev_path + "/device/../product");
        string manufacturer = read_line(dev_path + "/device/../manufacturer");
        if (!manufacturer.empty() || !product.empty())
            info.description = manufacturer + " " + product;
        else
            info.description = dev_name;

        // Try to read hardware ID (VID:PID)
        string vid = read_line(dev_path + "/device/../idVendor");
        string pid = read_line(dev_path + "/device/../idProduct");
        if (!vid.empty() && !pid.empty())
            info.hardware_id = "USB VID:PID=" + vid + ":" + pid;
        else
            info.hardware_id = "n/a";

        results.push_back(info);
    }

    // If no USB devices found, also check for common serial ports
    if (results.empty()) {
        const char* common_ports[] = {
            "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyUSB3",
            "/dev/ttyACM0", "/dev/ttyACM1",
            "/dev/ttyAMA0", "/dev/ttyAMA1",
            "/dev/ttyS0", "/dev/ttyS1",
            NULL
        };

        for (int i = 0; common_ports[i] != NULL; i++) {
            struct stat st;
            if (stat(common_ports[i], &st) == 0) {
                PortInfo info;
                info.port = common_ports[i];
                info.description = common_ports[i];
                info.hardware_id = "n/a";
                results.push_back(info);
            }
        }
    }

    return results;
}

#endif // !defined(_WIN32)
