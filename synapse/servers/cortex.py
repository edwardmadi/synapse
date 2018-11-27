import os
import sys
import argparse

import synapse.glob as s_glob

import synapse.common as s_common
import synapse.cortex as s_cortex
import synapse.daemon as s_daemon

teleport = os.getenv('SYN_CORTEX_PORT', '27492')
telehost = os.getenv('SYN_CORTEX_HOST', '127.0.0.1')

#httpport = os.getenv('SYN_CORTEX_HTTP_PORT', '80')
#httphost = os.getenv('SYN_CORTEX_HTTP_HOST', '127.0.0.1')

#httpsport = os.getenv('SYN_CORTEX_HTTPS_PORT', '443')
#httpshost = os.getenv('SYN_CORTEX_HTTPS_HOST', '127.0.0.1')

def main(argv):

    pars = argparse.ArgumentParser(prog='synapse.servers.cortex')

    pars.add_argument('--port', default=teleport, help='The TCP port to bind for telepath.')
    pars.add_argument('--host', default=telehost, help='The host address to bind telepath.')

    pars.add_argument('coredir', help='The directory for the cortex to use for storage.')

    opts = pars.parse_args(argv)

    dmon = s_glob.sync(mainopts(opts))

    return dmon.main()

async def mainopts(opts):

    proto = 'tcp'

    lisn = f'{proto}://{opts.host}:{opts.port}/cortex'

    conf = {
        'listen': lisn,
    }

    print('starting cortex at: %s' % (lisn,))

    path = s_common.gendir(opts.coredir, 'dmon')

    dmon = await s_daemon.Daemon.anit(path, conf=conf)
    core = await s_cortex.Cortex.anit(opts.coredir)

    dmon.share('cortex', core)
    dmon.onfini(core.fini)

    return dmon

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
