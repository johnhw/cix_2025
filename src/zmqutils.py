import zmq, json, sys
from multiprocessing import Process, Queue
import queue
import subprocess
import time

def json_encode(obj):
    return json.dumps(obj).encode("utf-8")

def json_decode(obj):
    return json.loads(obj.decode("utf-8"))

def async_req_loop(zmq_port, in_q, out_q):
    # Create an infinite loop that connects to a ZMQ port,
    # sends a request (from in_q), and waits for a response
    # (which is placed in out_q).
    # Messages are JSON encoded.
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect(f"tcp://localhost:{zmq_port}")
    while True:  
        try:
            request = in_q.get()
            #print("Got request")
            # get *all* waiting requests from the queue
            while not in_q.empty():
                request = in_q.get_nowait()
        except queue.Empty:
            pass
        
        socket.send(json_encode(request))
        #print("Send request")
        response = socket.recv()
        #print("Received response")
        try:
            out_q.put_nowait(json_decode(response))
            #print("Put response")
        except queue.Full:
            pass


def sync_rep_loop(zmq_port, fn, timeout=2000):
    # synchronous reply loop
    # Create an infinite loop that binds to a ZMQ port,
    # waits for a request, and sends a response using
    # the callback fn to process the request.
    # Messages are JSON encoded.
    context = zmq.Context() 
    socket = context.socket(zmq.REP)
    socket.bind(f"tcp://*:{zmq_port}")
    socket.setsockopt(zmq.RCVTIMEO, timeout)
    try:
        while True:
            try:
                message = socket.recv()
                response = fn(json_decode(message))
                socket.send(json_encode(response))
            except zmq.error.Again:
                pass
                #print("Timed out")
    except Exception as e:
        print(e)
    finally:
        socket.close()

def rep_loop_test(zmq_port):
    def print_respond(x):
        print(x)
        return {"response": "OK"}
    sync_rep_loop(zmq_port, print_respond)

def req_loop_feed(zmq_port, in_q, out_q):    
    # feed the req loop with some test data
    for i in range(10):
        in_q.put({"test": i})
        print(out_q.get())

def loop_test(zmq_port):
    in_q = Queue()
    out_q = Queue()
    # now the req loop is also in its own process
    process = Process(target=async_req_loop, args=(zmq_port, in_q, out_q))
    process.daemon = True
    process.start()

    # start the req loop tester in its own process
    process = Process(target=req_loop_feed, args=(zmq_port, in_q, out_q))
    process.daemon = True
    process.start()
    # now engage synchronous rep loop
    rep_loop_test(zmq_port)
    
def pub_loop(self, port, topic, pub_q):
    # take messages off pub_q as they arrive,
    # and publish on the given port/topic
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind(f"tcp://*:{port}")
    while True:
        message = pub_q.get()
        socket.send_multipart([topic, json_encode(message)])

def sub_loop(self, port, topic, sub_q):
    # subscribe to the given port/topic, and place
    # messages on sub_q as they arrive
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://localhost:{port}")
    socket.setsockopt_string(zmq.SUBSCRIBE, topic)
    while True:
        topic, message = socket.recv_multipart()
        sub_q.put(json_decode(message))
          

from sys import platform

def safe_launch(script_path, args=[], timeout=60, sudo=False):
    t = time.time()
    cmd = [sys.executable, script_path]
    if sudo:
        cmd = ['gksudo'] + cmd
    if platform == "linux" or platform == "linux2":
        process = subprocess.Popen(cmd + args, shell=True)
    else:
        process = subprocess.Popen(cmd + args, creationflags=subprocess.CREATE_NEW_CONSOLE)
    if timeout==0: # no block mode
        return
    while time.time() - t < timeout:
        if process.poll() is not None:
            return
        time.sleep(1)
    process.terminate()
    time.sleep(1)
    process.kill()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()


def start_test():
    # create a process for each of req_rep_loop and rep_loop_test
    # create queues, and then start the processes
    zmq_port = 5555
    loop_test(zmq_port)


# utils...
def prediction_loop(predict_fn, port=5556):
    # synchronous reply loop -- receive touch events and reply with predictions
    def loop_fn(touch_input):
        # respond to touch events
        if "touch" in touch_input:
            # decode it, predict and send a response
            x = np.array(touch_input["touch"]).astype(np.float32).reshape(1, 270)
            seq = touch_input["seq"]
            y = predict_fn(x)
            msg = {
                "target": {
                    "x": float(y[0, 0]),
                    "y": float(y[0, 1]),
                    "radius": float(y[0, 2]),
                },
                "seq": seq,
            }
            print(f"{seq}                     \r", end="")
            return msg
        # queue shutdown
        if "quit" in touch_input:
            raise StopIteration

    sync_rep_loop(port, loop_fn)

def launch_with_params(params, timeout=0):
    params["zmq_port"] = "5556"
    # launch the key demo with the interleaved parameters/values
    call_params = []
    for k, v in params.items():
        if v is not None:
            call_params.append(f"--{k}")
            call_params.append(str(v))
    safe_launch("src/key_demo.py", args=call_params, timeout=timeout)    

if __name__=="__main__":
    start_test()
