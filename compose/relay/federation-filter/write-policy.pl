#!/usr/bin/perl
# strfry write policy plugin: keeps this relay to its own federation.
#
#  - order events (kind 38383, NIP-69): only when signed by a federation coordinator;
#  - ratings (kind 31986): only when they rate (p tag) a federation coordinator;
#  - events that arrive by `strfry sync`/`stream` from another relay: only the kinds
#    listed in a "sync-kinds" line (if there is one). What clients and the coordinator
#    publish directly (gift wraps 1059, chat, account recovery...) is not affected.
#
# Config: /etc/strfry/allowed-order-pubkeys.txt
#   one coordinator hex pubkey per line (# comments allowed), plus optionally
#   sync-kinds 38383 31986
# It is re-read when its mtime, size or inode changes. With no pubkeys the plugin accepts everything
# (fail open) and warns on stderr.
#
# Edit the files in place, or restart the relay container: they are single-file
# bind mounts, so a replaced file (new inode) is not seen until a restart.
use strict;
use warnings;
use JSON::PP;

$| = 1;
my $LIST = $ENV{ALLOWED_ORDER_PUBKEYS} || '/etc/strfry/allowed-order-pubkeys.txt';
my $json = JSON::PP->new->utf8->canonical;
my (%allowed, %sync_kinds);
my $mtime = -1;

sub load_list {
    my @st = stat($LIST);
    my $m = @st ? "$st[9]:$st[7]:$st[1]" : "none";
    return if $m eq $mtime;
    $mtime = $m;
    %allowed = ();
    %sync_kinds = ();
    if (open(my $fh, '<', $LIST)) {
        while (my $l = <$fh>) {
            $l =~ s/#.*//;
            if ($l =~ /^\s*sync-kinds\s+(.*)$/) {
                $sync_kinds{$_} = 1 for ($1 =~ /(\d+)/g);
                next;
            }
            $l =~ s/\s+//g;
            $allowed{lc $l} = 1 if $l =~ /^[0-9a-fA-F]{64}$/;
        }
        close $fh;
    }
    print STDERR "write-policy: no pubkeys in $LIST, accepting everything\n" unless %allowed;
}

sub verdict {
    my ($req) = @_;
    my $ev = $req->{event} || {};
    my $kind = $ev->{kind} // -1;
    my $src = $req->{sourceType} // '';
    load_list();
    return ('accept', '') unless %allowed;
    if (($src eq 'Sync' || $src eq 'Stream') && %sync_kinds && !$sync_kinds{$kind}) {
        return ('reject', 'blocked: kind not synced from other relays');
    }
    if ($kind == 38383 && !$allowed{lc($ev->{pubkey} // '')}) {
        return ('reject', 'blocked: order events are only accepted from this federation');
    }
    if ($kind == 31986) {
        my @p = map { lc($_->[1] // '') } grep { ref $_ eq 'ARRAY' && ($_->[0] // '') eq 'p' } @{ $ev->{tags} || [] };
        return ('reject', 'blocked: ratings are only accepted for this federation')
            unless grep { $allowed{$_} } @p;
    }
    return ('accept', '');
}

while (my $line = <STDIN>) {
    my ($id, $action, $msg) = ('', 'accept', '');
    my $req = eval { $json->decode($line) };
    if (!$req) {
        ($id) = $line =~ /"id"\s*:\s*"([0-9a-f]{64})"/;
        $id //= '';
    } else {
        $id = ($req->{event} || {})->{id} // '';
        ($action, $msg) = eval { verdict($req) };
        ($action, $msg) = ('accept', '') unless defined $action;
    }
    my %res = (id => $id, action => $action);
    $res{msg} = $msg if $msg ne '';
    print $json->encode(\%res), "\n";
}
