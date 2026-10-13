package main

import (
	"fmt"
	"os"

	"github.com/intrusiveai-engineering/releases/internal/publishercli"
)

func main() {
	if err := publishercli.Run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
