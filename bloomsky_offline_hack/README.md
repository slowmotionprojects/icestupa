# Slow Motion hack: enabling an offline data processing workflow for the Ice Stupa weather station

For the past couple of weeks, [Slow Motion Projects](http://slowmotionprojects.org)
has been working with the [Ice Stupa](http://icestupa.org) team to understand how
man-made glaciers grow and melt, and down the line to design and dimension a
network of ice stupas to provide water for a whole terraformed valley in Ladakh,
hosting the future [Himalayan Institute of Alternatives](http://hial.co.in).

Pretty cool vision, huh? However, we're just at the beginning of the project, and
optimising the ice stupas requires, among many others, a steady stream of weather data.
Here we explain how we modified the existing data collection setup to allow weather
data to be continuously collected, even when the system is offline.

## Problem statement
Thanks to a sponsoring from [Bloomsky](https://www.bloomsky.com/), the Ice Stupa project
received a weather station that records environmental parameters and snaps a picture
every 5 minutes.

<p align="center">
<img width="300" src="https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/pictures/bloomsky_station.jpg" alt="Bloomsky weather station" hspace="20">
<img width="300" src="https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/pictures/icestupa_growth.gif" alt="Ice stupa growth animation" hspace="20">
</p>

These measurements and pictures are uploaded to a Bloomsky backend server via the
embedded WiFi connection, and available in near real-time through an app.
The crucial problem is that the system assumes constant Internet connectivity,
which is a pipe dream in remote mountain regions like Ladakh, where Internet access in
the whole valley may be cut off up to 50% of the time.
**When there is no Internet connection, weather data will simply be lost.**
For us, that was not acceptable; reaching out to Bloomsky tech support also did not
lead to a solution. **We had to find a way to enable offline storage of data, without
disrupting the existing system.**

## Limitations
We had very limited time to complete the project, and needed to work with the following
limitations in mind:
- no possibility to modify the station or alter its connection settings (other than
changing the network it connects to);
- no possibility to set up packet inspection/sniffing on the router;
- only equipment available: one Raspberry Pi 2 (without WiFi, so no option to set up
a wireless hotspot)

## Reverse-engineering the Bloomsky protocol
We connected the weather station to a temporary laptop hotspot and sniffed the network
traffic (with [Wireshark](https://www.wireshark.org)) to understand the handshake procedure and subsequent data exchange.

### Online mode
In this test setup, the weather station has the IP `192.168.2.5`, and the gateway is
`192.168.2.1`.

<p align="center">
<img width="800" src="https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/pictures/handshake.png" alt="Handshake and data transfer">
</p>

1. The station sends a DNS query for `bskybackend.bloomsky.com`, receives an IP address.
2. The station initiates a first TCP session, actually an HTTP POST request to `/devc/skydevice/?Info={"DeviceID"="XXX"}`,
and other device-specific information. **If, and only if** the Bloomsky backend replies with an HTTP 200 ("OK"),
the station starts transferring binary data (the latest picture) over TCP, and sends another HTTP POST request
containing the weather data (which is what we want to log -- more on this below).

### Offline mode

<p align="center">
<img width="800" src="https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/pictures/connection%20failure.png" alt="Connection failure">
</p>

When the station is offline, it will just continuously query an unreachable DNS server, and **won't send any data**
(the lost data also won't be retrieved later when the connection to the server is re-established).

## Our solution

### Step-by-step

In order to enable continous data transfer, regardless of Internet connectivity, we will need to:

1. Impersonate the Bloomsky backend to intercept the packets sent to it by the weather station;
2. Pretend the backend is online, even if it isn't;
3. Mimic the communication protocol when the backend is offline, to fool the station into sending data;
4. Do all this without disrupting the normal function, so that the data sent while the station is online can still
be available via the Bloomsky mobile app.

This will be done by setting up on a local server (Raspberry Pi):
- **a fake DNS server**, which redirects queries to `bskybackend.bloomsky.com` to itself, with a passthrough for all other queries
- **a transparent TCP proxy** between the station and the backend, which will log the weather data sent by the station, and mimic
the backend when the station is offline.

### Implementation

#### Fake DNS server

We used Crypt0s' [FakeDns server](https://github.com/Crypt0s/FakeDns) with minor modifications. The server
([fake_dns.py](fake_dns.py)) simply listens on port 53 for any incoming DNS query, and emulates a restricted set of
DNS records found in [dns.conf](dns.conf). Other requests are passed to a real DNS (`8.8.8.8`, one of Google's DNS servers).
In our case, the configuration file contains one record only: IP address (DNS lookup type 'A') for domain `bskybackend.bloomsky.com`,
with a value set to the local IP of our Raspberry Pi server.

#### TCP proxy with packet logging

##### Bidirectional operation

This step is slightly more involved than the previous one. We adapted Marina VonStein's brilliantly simple
[TCP proxy](http://bt3gl.github.io/black-hat-python-networking-the-socket-module.html) code, which includes a light threaded
TCP proxy server written in Python. In our implementation, it waits for an incoming connection from
a local host (on a specific port), and after receiving the connection it establishes a symmetrical
connection to a remote host (also on a specific port), acting as a transparent proxy.
Both incoming and outgoing packets go through handler functions. In our case, if the
outgoing TCP buffer contains a string (we avoid processing images), we keep lines starting with `POST` (HTTP method),
and write them to a file on the disk ([request_handler](https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/tcp_proxy.py#L72-L80) function).

Each of these lines contains a full data frame, wrapped in a single HTTP query:
```
POST /devc/skydevice/?Info={"DeviceID":"XXX","FWVersion1":"1.4.0","FWVersion2":"1.2.4","HWVersion":"1.0.1","DeviceType":"SKY1","Temperature":16.33,"Humidity":34,"Voltage":2586,"UVIndex":1234,"Luminance":2689636,"Rain":0,"Pressure":669,"ChargerStatus":0,"TS":1480867686} HTTP/1.1
```

##### Offline mode

The above only works when connection to the remote can be established, i.e. we're online. To enable offline operation, we
cache the latest received response from the remote server in a file on the disk; it will look like this (but varies):
```
HTTP/1.1 200 OK
Allow: POST, OPTIONS
Content-Type: application/json;charset=utf-8
Date: Mon, 05 Dec 2016 03:36:31 GMT
Server: Apache/2.4.23 (Amazon) mod_wsgi/3.5 Python/2.7.10
Vary: Accept
X-Frame-Options: SAMEORIGIN
transfer-encoding: chunked
Connection: Close

62
{"ResponseValue":200,"Message":0,"SunsetTime":1480938629,"TS":1480908995,"SunriseTime":1480900578}
0
```

When the connection to the remote socket fails, the proxy switches to "offline mode" and continuously sends back the same
cached frame to the local host, while updating the time stamps (lines 4 and 12 in the above request).
This is a very crude approximation of the real Bloomsky communication protocol, but it's enough to fool the station into
thinking it is indeed talking to the Bloomsky backend.

In summary:
- the weather station thinks it's communicating with the backend;
- the backend thinks it's communicating with the weather station;
- in practice, they are none the wiser as both go through our proxy, which implements selective packet logging and
mimics the backend when offline.

## In practice

### Prerequisites

- Enable fixed IP addresses (through the router's DHCP configuration) for the weather station
and the Raspberry Pi; here, the Pi is `192.168.1.29` and the station is `192.168.1.30`.
- Route all DNS queries to the fake DNS server, with a fallback to a real DNS server. On a D-Link router, this is
accessible through the menu Advanced -> DNS setup.

<p align="center">
<img width="300" src="https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/pictures/dns%20config.png" alt="DNS configuration">
</p>

### Running the server

Both servers (DNS and proxy) require administrative privileges, as they use restricted ports (53 and 80).
The IP of the real backend to (in the call to [tcp_proxy.py](tcp_proxy.py)) redirect traffic to can be obtained with `nslookup bskybackend.bloomsky.com 8.8.8.8`
(careful: if a real DNS server is not passed to nslookup as argument, the response will be our local DNS!).

#### Online operation

<p align="center">
<img width="650" src="https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/pictures/online%20operation.png" alt="Online operation">
</p>

1. The DNS server intercepts a DNS query, redirects traffic to itself
2. The local host starts sending data
3. Data is processed by the proxy and passed on to the remote host
4. The remote responds, the response is passed to the local host
5. At least one TCP buffer is empty, the exchange stops (will start again 5 minutes later).

#### Offline operation

<p align="center">
<img width="650" src="https://github.com/slowmotionprojects/icestupa/blob/master/bloomsky_offline_hack/pictures/offline%20operation.png" alt="Offline operation">
</p>

The workflow is the same as above, except that connecting to the remote socket fails; the TCP proxy
(which has now become the backend) sends the previously cached HTTP frame in response to every request sent by the local host,
triggering the data transfer.

## It works! *Habemus datum*.

Now on to doing some science with this data...