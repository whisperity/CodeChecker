
Refactorings applied
--------------------

Unfortunately, the existing code could not be cleanly modified to support this new architecture, so I had to implement some significant (and less significant) refactorings before the new feature could be added.

 * There were about 3 or 4 different ways of generating a _random string_ in the `server` package. These has been unified.
 * a5119f04ea21dd6dda927d962fa1bc892131db9f (_Run storage limit_) changed the previous **authentication** config into a generic _server_ config, but unfortunately all of the access to the configuration options were done through the `SessionManager` object, which thus became a massive misnomer. This was refactored to a dedicated `ServerConfiguration` object which deals with accessing the configuration, and a `SessionManager` returned to be truly what the name would suggest.