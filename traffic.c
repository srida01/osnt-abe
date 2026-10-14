#define _POSIX_C_SOURCE 200809L

#include <msquic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdatomic.h>
#include <time.h>

static const QUIC_API_TABLE *Q;
static HQUIC Registration, Configuration, Connection, Stream;

static atomic_int Connected;
static atomic_int Done;
static atomic_int StopSending;
static atomic_int Failed;

static int Server;
static double StartTime;

static QUIC_BUFFER Buffers[4];
static uint8_t Data[4][65536];

static double
Now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static void
Pause(void)
{
    struct timespec t = {0, 20000000};
    nanosleep(&t, NULL);
}

static void
Check(QUIC_STATUS status, const char *operation)
{
    if (QUIC_FAILED(status)) {
        fprintf(
            stderr, "%s failed: 0x%x\n",
            operation, (unsigned)status
        );
        exit(2);
    }
}

static QUIC_STATUS QUIC_API
StreamCallback(
    HQUIC stream,
    void *context,
    QUIC_STREAM_EVENT *event
)
{
    (void)context;

    if (
        event->Type == QUIC_STREAM_EVENT_SEND_COMPLETE &&
        !event->SEND_COMPLETE.Canceled &&
        !atomic_load(&StopSending)
    ) {
        QUIC_BUFFER *buffer =
            event->SEND_COMPLETE.ClientContext;

        QUIC_STATUS status = Q->StreamSend(
            stream, buffer, 1,
            QUIC_SEND_FLAG_NONE, buffer
        );

        if (QUIC_FAILED(status)) {
            atomic_store(&Failed, 1);
            atomic_store(&StopSending, 1);
        }
    }

    if (event->Type == QUIC_STREAM_EVENT_SHUTDOWN_COMPLETE) {
        Q->StreamClose(stream);
    }

    return QUIC_STATUS_SUCCESS;
}

static QUIC_STATUS QUIC_API
ConnectionCallback(
    HQUIC connection,
    void *context,
    QUIC_CONNECTION_EVENT *event
)
{
    (void)context;

    switch (event->Type) {
    case QUIC_CONNECTION_EVENT_CONNECTED:
        if (!Server) {
            Check(
                Q->StreamOpen(
                    connection,
                    QUIC_STREAM_OPEN_FLAG_UNIDIRECTIONAL,
                    StreamCallback, NULL, &Stream
                ),
                "StreamOpen"
            );

            Check(
                Q->StreamStart(
                    Stream,
                    QUIC_STREAM_START_FLAG_IMMEDIATE
                ),
                "StreamStart"
            );

            StartTime = Now();

            for (int i = 0; i < 4; i++) {
                Check(
                    Q->StreamSend(
                        Stream, &Buffers[i], 1,
                        QUIC_SEND_FLAG_NONE, &Buffers[i]
                    ),
                    "StreamSend"
                );
            }

            atomic_store(&Connected, 1);
        }
        break;

    case QUIC_CONNECTION_EVENT_PEER_STREAM_STARTED:
        Q->SetCallbackHandler(
            event->PEER_STREAM_STARTED.Stream,
            (void *)StreamCallback,
            NULL
        );
        break;

    case QUIC_CONNECTION_EVENT_SHUTDOWN_INITIATED_BY_TRANSPORT:
        fprintf(
            stderr, "Transport shutdown: 0x%x\n",
            (unsigned)event->SHUTDOWN_INITIATED_BY_TRANSPORT.Status
        );

        if (!atomic_load(&StopSending)) {
            atomic_store(&Failed, 1);
        }

        atomic_store(&StopSending, 1);
        break;

    case QUIC_CONNECTION_EVENT_SHUTDOWN_INITIATED_BY_PEER:
        if (!Server && !atomic_load(&StopSending)) {
            atomic_store(&Failed, 1);
        }

        atomic_store(&StopSending, 1);
        break;

    case QUIC_CONNECTION_EVENT_SHUTDOWN_COMPLETE:
        if (Server) {
            Q->ConnectionClose(connection);
        } else {
            atomic_store(&Done, 1);
        }
        break;

    default:
        break;
    }

    return QUIC_STATUS_SUCCESS;
}

static QUIC_STATUS QUIC_API
ListenerCallback(
    HQUIC listener,
    void *context,
    QUIC_LISTENER_EVENT *event
)
{
    (void)listener;
    (void)context;

    if (event->Type == QUIC_LISTENER_EVENT_NEW_CONNECTION) {
        Q->SetCallbackHandler(
            event->NEW_CONNECTION.Connection,
            (void *)ConnectionCallback,
            NULL
        );

        return Q->ConnectionSetConfiguration(
            event->NEW_CONNECTION.Connection,
            Configuration
        );
    }

    return QUIC_STATUS_SUCCESS;
}

int
main(int argc, char **argv)
{
    if (argc < 2) {
        return 2;
    }

    Server = !strcmp(argv[1], "server");

    if (
        (Server && argc != 5) ||
        (!Server && argc != 7)
    ) {
        fprintf(
            stderr,
            "server PORT CERT KEY\n"
            "client HOST PORT SECONDS ECN CSV\n"
        );
        return 2;
    }

    int ecn = Server ? 0 : atoi(argv[5]);

    for (int i = 0; i < 4; i++) {
        Buffers[i].Length = sizeof(Data[i]);
        Buffers[i].Buffer = Data[i];
    }

    Check(MsQuicOpen2(&Q), "MsQuicOpen2");

    QUIC_REGISTRATION_CONFIG registrationConfig = {
        "msquic-lab",
        QUIC_EXECUTION_PROFILE_LOW_LATENCY
    };

    Check(
        Q->RegistrationOpen(
            &registrationConfig, &Registration
        ),
        "RegistrationOpen"
    );

    QUIC_BUFFER alpn = {
        10, (uint8_t *)"msquic-lab"
    };

    QUIC_SETTINGS settings = {0};

    settings.IsSet.EcnEnabled = 1;
    settings.EcnEnabled = ecn;

    settings.IsSet.CongestionControlAlgorithm = 1;
    settings.CongestionControlAlgorithm =
        QUIC_CONGESTION_CONTROL_ALGORITHM_CUBIC;

    /*
     * Keep application buffers until acknowledged so SEND_COMPLETE
     * recycling does not create an unbounded buffered send queue.
     */
    settings.IsSet.SendBufferingEnabled = 1;
    settings.SendBufferingEnabled = 0;

    settings.IsSet.PeerUnidiStreamCount = 1;
    settings.PeerUnidiStreamCount = 4;

    settings.IsSet.IdleTimeoutMs = 1;
    settings.IdleTimeoutMs = 30000;

    settings.IsSet.StreamRecvWindowDefault = 1;
    settings.StreamRecvWindowDefault = 8 * 1024 * 1024;

    settings.IsSet.ConnFlowControlWindow = 1;
    settings.ConnFlowControlWindow = 32 * 1024 * 1024;

    Check(
        Q->ConfigurationOpen(
            Registration,
            &alpn, 1,
            &settings, sizeof(settings),
            NULL, &Configuration
        ),
        "ConfigurationOpen"
    );

    QUIC_CREDENTIAL_CONFIG credentials = {0};
    QUIC_CERTIFICATE_FILE certificate = {0};

    if (Server) {
        certificate.CertificateFile = argv[3];
        certificate.PrivateKeyFile = argv[4];

        credentials.Type =
            QUIC_CREDENTIAL_TYPE_CERTIFICATE_FILE;
        credentials.CertificateFile = &certificate;
    } else {
        credentials.Type = QUIC_CREDENTIAL_TYPE_NONE;

        /* Self-signed certificate in this isolated local lab only. */
        credentials.Flags =
            QUIC_CREDENTIAL_FLAG_CLIENT |
            QUIC_CREDENTIAL_FLAG_NO_CERTIFICATE_VALIDATION;
    }

    Check(
        Q->ConfigurationLoadCredential(
            Configuration, &credentials
        ),
        "ConfigurationLoadCredential"
    );

    if (Server) {
        HQUIC listener;
        QUIC_ADDR address = {0};

        QuicAddrSetFamily(
            &address, QUIC_ADDRESS_FAMILY_INET
        );
        QuicAddrSetPort(&address, atoi(argv[2]));

        Check(
            Q->ListenerOpen(
                Registration,
                ListenerCallback,
                NULL, &listener
            ),
            "ListenerOpen"
        );

        Check(
            Q->ListenerStart(
                listener, &alpn, 1, &address
            ),
            "ListenerStart"
        );

        puts("READY");
        fflush(stdout);

        for (;;) {
            Pause();
        }
    }

    FILE *csv = fopen(argv[6], "w");

    if (!csv) {
        perror("CSV");
        return 2;
    }

    fprintf(
        csv,
        "time_s,cwnd_bytes,rtt_us,sent_bytes,"
        "lost_packets,ecn_capable,ecn_congestion_events\n"
    );
    fflush(csv);

    Check(
        Q->ConnectionOpen(
            Registration,
            ConnectionCallback,
            NULL, &Connection
        ),
        "ConnectionOpen"
    );

    Check(
        Q->ConnectionStart(
            Connection,
            Configuration,
            QUIC_ADDRESS_FAMILY_INET,
            argv[2],
            atoi(argv[3])
        ),
        "ConnectionStart"
    );

    double deadline = Now() + 15;

    while (
        !atomic_load(&Connected) &&
        !atomic_load(&Done) &&
        Now() < deadline
    ) {
        Pause();
    }

    if (!atomic_load(&Connected)) {
        fprintf(stderr, "Handshake failed or timed out\n");
        return 3;
    }

    double duration = atof(argv[4]);

    while (
        !atomic_load(&Done) &&
        !atomic_load(&StopSending) &&
        Now() - StartTime < duration
    ) {
        QUIC_STATISTICS_V2 statistics = {0};
        uint32_t length = sizeof(statistics);

        QUIC_STATUS status = Q->GetParam(
            Connection,
            QUIC_PARAM_CONN_STATISTICS_V2,
            &length,
            &statistics
        );

        size_t required =
            offsetof(
                QUIC_STATISTICS_V2,
                SendEcnCongestionCount
            ) +
            sizeof(statistics.SendEcnCongestionCount);

        if (QUIC_FAILED(status) || length < required) {
            fprintf(
                stderr,
                "Statistics unavailable or older library loaded\n"
            );
            atomic_store(&Failed, 1);
            break;
        }

        fprintf(
            csv,
            "%.6f,%u,%u,%llu,%llu,%u,%u\n",
            Now() - StartTime,
            statistics.SendCongestionWindow,
            statistics.Rtt,
            (unsigned long long)statistics.SendTotalBytes,
            (unsigned long long)statistics.SendSuspectedLostPackets,
            statistics.EcnCapable,
            statistics.SendEcnCongestionCount
        );

        fflush(csv);
        Pause();
    }

    atomic_store(&StopSending, 1);

    Q->ConnectionShutdown(
        Connection,
        QUIC_CONNECTION_SHUTDOWN_FLAG_NONE,
        0
    );

    deadline = Now() + 10;

    while (!atomic_load(&Done) && Now() < deadline) {
        Pause();
    }

    fclose(csv);

    if (!atomic_load(&Done)) {
        return 4;
    }

    Q->ConnectionClose(Connection);
    Q->ConfigurationClose(Configuration);
    Q->RegistrationClose(Registration);
    MsQuicClose(Q);

    return atomic_load(&Failed) ? 5 : 0;
}
