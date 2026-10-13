package publishercli

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"

	"github.com/intrusiveai-engineering/releases/internal/catalogcli"
	"github.com/intrusiveai-engineering/releases/internal/oci"
	"github.com/intrusiveai-engineering/releases/internal/record"
	"github.com/intrusiveai-engineering/releases/internal/remote"
)

func Run(arguments []string) error {
	if len(arguments) < 2 {
		return errors.New("expected a command and subcommand")
	}
	switch arguments[0] + " " + arguments[1] {
	case "record validate":
		set := flag.NewFlagSet("record validate", flag.ContinueOnError)
		file := set.String("file", "", "record JSON file")
		if err := set.Parse(arguments[2:]); err != nil {
			return err
		}
		if *file == "" || set.NArg() != 0 {
			return errors.New("record validate requires --file")
		}
		raw, err := os.ReadFile(*file)
		if err != nil {
			return fmt.Errorf("read record: %w", err)
		}
		if _, err := record.Parse(raw); err != nil {
			return err
		}
		fmt.Println("record is valid")
		return nil
	case "image verify":
		set := flag.NewFlagSet("image verify", flag.ContinueOnError)
		reference := set.String("reference", "", "tagged GHCR image reference")
		platform := set.String("platform", "", "qualified linux platform")
		manifest := set.String("manifest-digest", "", "platform manifest digest")
		config := set.String("config-digest", "", "platform image config digest")
		index := set.String("index-digest", "", "optional multi-platform index digest")
		source := set.String("source", "https://github.com/intrusiveai/attack_harness", "expected OCI source URL")
		if err := set.Parse(arguments[2:]); err != nil {
			return err
		}
		if *reference == "" || *platform == "" || *manifest == "" || *config == "" || set.NArg() != 0 {
			return errors.New("image verify requires --reference, --platform, --manifest-digest, and --config-digest")
		}
		if err := (oci.Verifier{}).Verify(context.Background(), *reference, *platform, *manifest, *config, *index, *source); err != nil {
			return err
		}
		fmt.Println("public image identity is valid")
		return nil
	case "remote verify":
		set := flag.NewFlagSet("remote verify", flag.ContinueOnError)
		origin := set.String("origin", "", "HTTPS release origin")
		file := set.String("record", "", "expected record JSON file")
		missing := set.String("missing-digest", "", "unpublished digest to assert is 404")
		if err := set.Parse(arguments[2:]); err != nil {
			return err
		}
		if *origin == "" || *file == "" || set.NArg() != 0 {
			return errors.New("remote verify requires --origin and --record")
		}
		raw, err := os.ReadFile(*file)
		if err != nil {
			return fmt.Errorf("read expected record: %w", err)
		}
		if err := remote.Verify(context.Background(), *origin, raw, *missing); err != nil {
			return err
		}
		fmt.Println("remote release endpoint is valid")
		return nil
	default:
		return catalogcli.Run(arguments)
	}
}
