#!/usr/bin/env python

"""
TCP proxy, adapted from http://bt3gl.github.io/black-hat-python-networking-the-socket-module.html
Establishes a bidirectional connection between two machines (local & remote), and transfers packets from local to remote
as long as they keep coming. If a connection to remote can not be established, the proxy pretends it is alive remote by
by replying to local with the last HTTP response received from remote, with updated time stamps.
"""

import socket
import threading
import sys
import datetime
import pytz
from time import gmtime, strftime


def human_timestamp():
    """
    Prints current time with microsecond precision and system timezone
    Returns: str
    """
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f ') + strftime('%Z', gmtime())


def update_response(response):
    """
    Edits a string (HTTP request) to update the Date line and TS field
    Args:
        response: str
    Returns: str
    """
    response = '\n'.join(edit_response_lines(response.splitlines()))
    return response


def edit_response_lines(lines):
    dtnow = pytz.timezone('GMT').localize(datetime.datetime.utcnow())
    for line in lines:
        if (not line.startswith('Date')) and (not line.startswith('{"ResponseValue"')):
            yield line
        elif line.startswith('Date'):
            yield 'Date: %s' % dtnow.strftime('%a, %d %b %Y %H:%M:%S %Z')
        elif line.startswith('{"ResponseValue"'):
            try:
                comps = line.split('"TS":')
                l1 = comps[0] + '"TS":'
                l2 = dtnow.strftime('%s') + ','
                l3 = ','.join(comps[1].split(',')[1:])
                yield l1+l2+l3
            except:
                yield line


# Used for receiving local and remote data, and pass in the socket object.
def receive_from(connection):
    buffer_ = ''

    # set timeout
    connection.settimeout(5)
    try:
        while True:
            data = connection.recv(4096)
            if not data:
                break
            buffer_ += data
    except:
        pass
    return buffer_


def request_handler(buffer):
    # perform packet modifications
    if isinstance(buffer, str):
        with open('POST_requests.txt', 'a') as f:
            post_requests = [line for line in buffer.splitlines() if line.strip().startswith('POST')]
            for pr in post_requests:
                f.write(pr if pr.endswith('\n') else (pr+'\n'))
            f.close()
    return buffer


def response_handler(buffer):
    # perform packet modifications
    return buffer


def proxy_handler(client_socket, remote_host, remote_port):

    remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        remote_socket.connect((remote_host, remote_port))
        offline = False
    except:
        print "[%s] Couldn't open remote socket; connection possibly offline" % human_timestamp()
        offline = True

    # loop and read from local, send to remote, send to local
    while True:
        local_buffer = receive_from(client_socket)
        if len(local_buffer):
            print "[%s] Received %d bytes from localhost" % (human_timestamp(), len(local_buffer))

            # send it to our request handler
            local_buffer = request_handler(local_buffer)

            if not offline:
                # send off the data to the remote host
                remote_socket.send(local_buffer)
                print "[%s] Sent to remote" % human_timestamp()

        if not offline:
            remote_buffer = receive_from(remote_socket)
            if len(remote_buffer):
                if isinstance(remote_buffer, str):
                    with open('last_response.txt', 'w') as f:
                        f.write(remote_buffer)
                        f.close()
        else:
            with open('last_response.txt', 'r') as f:
                remote_buffer = f.read()
                f.close()
                remote_buffer = update_response(remote_buffer)

        if len(remote_buffer):
            print "[%s] Received %d bytes from remote%s" % (human_timestamp(), len(remote_buffer), ' (offline)' if offline else '')

            # send it to our response handler
            remote_buffer = response_handler(remote_buffer)

            # send off the data to the remote host
            client_socket.send(remote_buffer)
            print "[%s] Sent to localhost" % human_timestamp()

        if not len(local_buffer) or not len(remote_buffer):
            client_socket.close()
            remote_socket.close()
            print "[%s] No more data; closing connections" % human_timestamp()
            break


def server_loop(local_host, local_port, remote_host, remote_port):

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        server.bind((local_host, local_port))
    except:
        print "[%s] Failed to listen on %s:%d" % (human_timestamp(), local_host, local_port)
        sys.exit()

    print "[%s] Listening on %s:%d" % (human_timestamp(), local_host, local_port)
    server.listen(5)

    while True:
        client_socket, addr = server.accept()
        print "[%s] Received incoming connection from %s:%d" % (human_timestamp(), addr[0], addr[1])

        # start a thread to talk to the remote host
        proxy_thread = threading.Thread(target=proxy_handler, args=(client_socket, remote_host, remote_port))
        proxy_thread.start()


def main():

    if len(sys.argv[1:]) != 4:
        print "Usage: ./proxy.py <localhost> <localport> <remotehost> <remoteport>"
        print "Example: ./proxy.py 127.0.0.1 9000 10.12.122.1 9999"
        sys.exit()

    # setup local remote target
    local_host = sys.argv[1]
    if local_host == '0.0.0.0':
        local_host = ''
    local_port = int(sys.argv[2])

    # setup remote target
    remote_host = sys.argv[3]
    remote_port = int(sys.argv[4])

    # run the listening socket
    server_loop(local_host, local_port, remote_host, remote_port)

if __name__ == '__main__':
    main()
