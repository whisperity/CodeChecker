Refactorings applied
--------------------

Unfortunately, the existing code could not be cleanly modified to support this new architecture, so I had to implement some significant (and less significant) refactorings before the new feature could be added.

 * There were about 3 or 4 different ways of generating a _random string_ in the `server` package. These has been unified.
 * a5119f04ea21dd6dda927d962fa1bc892131db9f (_Run storage limit_) changed the previous **authentication** config into a generic _server_ config, but unfortunately all of the access to the configuration options were done through the `SessionManager` object, which thus became a massive misnomer. This was refactored to a dedicated `ServerConfiguration` object which deals with accessing the configuration, and a `SessionManager` returned to be truly what the name would suggest.

Anamnesis
---------

Even though d91547313e8eeaeea0af91744f280a2cc0c45294 introduced a socket-based keepalive into the server's implementation, this was not enough to **deterministically** fix `CodeChecker store` client-side hangs when the server took a long time processing the to-be-stored data.
The reason for this is not entirely clear, but has to do something with the inability to actually configure the networking parameters over a longer path, e.g., between data centres.
The symptoms were the same even with `keepalive` turned on: the client process hung on `read(4, ...)`, which was the low-level call to read from the opened TCP socket.
After the server finished processing API request `massStoreRun`, the reply it sent never reached the client, and as such, the client never exited from waiting, keeping the command-line occupied, and thus, blocking things like longer CI pipelines.