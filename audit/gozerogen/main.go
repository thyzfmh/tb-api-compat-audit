package main

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
)

type FieldShape struct {
	Name      string `json:"name"`
	JsonName  string `json:"jsonName"`
	OmitEmpty bool   `json:"omitempty"`
	GoType    string `json:"goType"`
	Kind      string `json:"kind"`
	ZeroWire  string `json:"zeroWire"`
}

func main() {
	out := map[string]interface{}{}
	for _, at := range registry2() {
		key := at.GV + "::" + at.Name
		shapes := map[string]FieldShape{}
		analyzeStruct(at.Type, shapes)
		zero := reflect.New(at.Type).Interface()
		b, err := json.Marshal(zero)
		actual := "ERR:" + fmt.Sprint(err)
		if err == nil {
			actual = string(b)
		}
		out[key] = map[string]interface{}{
			"fields":      shapes,
			"zeroMarshal": actual,
		}
	}
	b, _ := json.MarshalIndent(out, "", " ")
	fmt.Println(string(b))
}

func analyzeStruct(t reflect.Type, out map[string]FieldShape) {
	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		if f.PkgPath != "" {
			continue
		}
		tag := f.Tag.Get("json")
		if tag == "-" {
			continue
		}
		parts := strings.Split(tag, ",")
		jsonName := parts[0]
		omitEmpty := len(parts) > 1 && parts[1] == "omitempty"
		if jsonName == "" && f.Anonymous {
			ft := f.Type
			if ft.Kind() == reflect.Ptr {
				ft = ft.Elem()
			}
			if ft.Kind() == reflect.Struct {
				analyzeStruct(ft, out)
				continue
			}
		}
		out[f.Name] = FieldShape{
			Name: f.Name, JsonName: jsonName, OmitEmpty: omitEmpty,
			GoType: f.Type.String(), Kind: kindOf(f.Type),
			ZeroWire: zeroShape(f.Type, omitEmpty),
		}
	}
}

func kindOf(t reflect.Type) string {
	switch t.Kind() {
	case reflect.Ptr:
		return "ptr"
	case reflect.Slice:
		return "slice"
	case reflect.Map:
		return "map"
	case reflect.Struct:
		return "struct"
	case reflect.String:
		return "string"
	case reflect.Bool:
		return "bool"
	case reflect.Int32:
		return "int32"
	case reflect.Int64:
		return "int64"
	default:
		return t.Kind().String()
	}
}

func zeroShape(t reflect.Type, omitEmpty bool) string {
	k := t.Kind()
	if omitEmpty {
		switch k {
		case reflect.Ptr, reflect.Slice, reflect.Map, reflect.String, reflect.Bool:
			return "absent"
		case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64,
			reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64, reflect.Float32, reflect.Float64:
			return "absent"
		case reflect.Struct:
			return "present_full"
		}
	}
	switch k {
	case reflect.Ptr, reflect.Slice, reflect.Map:
		return "null"
	case reflect.String:
		return `""`
	case reflect.Bool:
		return "false"
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64,
		reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return "0"
	case reflect.Struct:
		return "present_full"
	case reflect.Interface:
		return "null"
	}
	return "?"
}
